import base64
import hashlib
import os
import platform
import sys
import tempfile
import traceback
import time
import builtins as _builtins


# CHIRP desktop installs gettext's conventional "_" helper globally.
# Some bundled and third-party drivers reference _() without importing it.
# PocketCHIRP has no wx gettext bootstrap, so provide an identity translator.
if not hasattr(_builtins, "_"):
    _builtins._ = lambda message: message

_last_image_bytes = b""
_last_raw_bytes = b""
_last_hash_info = ""


POCKETCHIRP_BRIDGE_REVISION = "264-p245-driver-roundtrip-uppercase-fallback"
POCKETCHIRP_APP_VERSION = "2.0.0"
POCKETCHIRP_INTERFACE_COMPAT = 1


# =============================================================================
# POCKETCHIRP PYSERIAL IMPORT-COMPATIBILITY SHIM - WEBCHIRP IMPROVEMENT #2
# =============================================================================
# WHY:
# A small number of CHIRP drivers import "serial" (pyserial) at module-import
# time even though PocketCHIRP supplies the actual radio I/O object through
# AndroidSerialPipe.  Chaquopy does not need a real OS pyserial port for those
# drivers, but without an import-compatible module they can fail to register.
#
# SAFETY:
# - If real pyserial is installed, leave it completely untouched.
# - The fallback shim provides only standard constants/exceptions needed while
#   importing drivers.
# - serial.Serial(...) deliberately FAILS CLOSED; it can never bypass
#   PocketCHIRP's AndroidSerialPipe and open a device behind our transport.
#
# REVERT:
# Set POCKETCHIRP_ENABLE_PYSERIAL_SHIM = False, or remove this entire block.
# Normal AndroidSerialPipe operation is otherwise unchanged.
# =============================================================================
POCKETCHIRP_ENABLE_PYSERIAL_SHIM = True


def _install_pocketchirp_pyserial_import_shim():
    if not POCKETCHIRP_ENABLE_PYSERIAL_SHIM:
        return False

    try:
        import serial  # noqa: F401
        return False
    except ImportError:
        pass

    import types as _pc_types

    shim = _pc_types.ModuleType("serial")
    shim.__doc__ = (
        "Minimal pyserial import-compatibility module for PocketCHIRP. "
        "Actual radio I/O is provided by AndroidSerialPipe."
    )

    shim.FIVEBITS = 5
    shim.SIXBITS = 6
    shim.SEVENBITS = 7
    shim.EIGHTBITS = 8

    shim.PARITY_NONE = "N"
    shim.PARITY_EVEN = "E"
    shim.PARITY_ODD = "O"
    shim.PARITY_MARK = "M"
    shim.PARITY_SPACE = "S"

    shim.STOPBITS_ONE = 1
    shim.STOPBITS_ONE_POINT_FIVE = 1.5
    shim.STOPBITS_TWO = 2

    class SerialException(OSError):
        pass

    class SerialTimeoutException(SerialException):
        pass

    class Serial:
        def __init__(self, *args, **kwargs):
            raise SerialException(
                "PocketCHIRP does not expose a native pyserial port; "
                "radio I/O must use AndroidSerialPipe"
            )

    shim.SerialException = SerialException
    shim.SerialTimeoutException = SerialTimeoutException
    shim.Serial = Serial

    sys.modules["serial"] = shim
    return True


_install_pocketchirp_pyserial_import_shim()


def pocketchirp_bridge_revision():
    return POCKETCHIRP_BRIDGE_REVISION

def pocketchirp_bridge_compat_version():
    """Compatibility level for the Java/Python/editor API contract."""
    return POCKETCHIRP_INTERFACE_COMPAT

def get_last_image_bytes():
    """Return the last complete CHIRP image as raw bytes."""
    return bytes(_last_image_bytes or b"")








def _set_transport_timeout_ms(transport, milliseconds):
    """Best-effort timeout hint for older/alternate transport shims.

    Some PocketCHIRP transport objects do not expose setTimeoutMs(). Timeout
    tuning is advisory; lack of that optional method must not abort a radio
    handshake before the driver gets a chance to communicate.
    """
    setter = getattr(transport, "setTimeoutMs", None)
    if callable(setter):
        setter(max(1, int(milliseconds)))
        return True
    return False

class AndroidSerialPipe:
    """pyserial-compatible wrapper around PocketCHIRP's Android transport."""

    PARITY_NONE = "N"
    PARITY_EVEN = "E"
    PARITY_ODD = "O"
    PARITY_MARK = "M"
    PARITY_SPACE = "S"

    STOPBITS_ONE = 1
    STOPBITS_ONE_POINT_FIVE = 1.5
    STOPBITS_TWO = 2

    FIVEBITS = 5
    SIXBITS = 6
    SEVENBITS = 7
    EIGHTBITS = 8

    def __init__(self, java_transport):
        self._transport = java_transport

        # CHIRP has radio-specific behavior for BLE serial links. On Unix-like
        # platforms its platform.is_ble_serial() check recognizes /tmp/ttyBLE*.
        # PocketCHIRP is not backed by a real tty, so expose a synthetic port
        # name only for the BLE transport. USB remains exactly as before.
        is_ble = False
        try:
            checker = getattr(java_transport, "isBleTransport", None)
            if callable(checker):
                is_ble = bool(checker())
        except Exception:
            # Compatibility with older Java transports: fail back to the
            # historical PocketCHIRP serial identity rather than guessing BLE.
            is_ble = False

        self.is_ble = is_ble

        # isBleTransport() is already normalized by the proprietary Binder:
        # true means CHIRP should use native/direct-BLE semantics; false means
        # ordinary serial semantics. No programmer/profile identity crosses here.
        self.is_direct_ble = bool(is_ble)
        if self.is_direct_ble:
            self.port = "/tmp/ttyBLE-PocketCHIRP"
            self.name = "/tmp/ttyBLE-PocketCHIRP"
        else:
            self.port = "PocketCHIRP"
            self.name = "PocketCHIRP"
        self.is_open = True
        # Match CHIRP desktop's serial-open contract. Drivers which require a
        # different timeout change pipe.timeout themselves.
        self._timeout = 0.25
        self._write_timeout = 1.5
        self._baudrate = 9600
        self._bytesize = 8
        self._parity = "N"
        self._stopbits = 1
        self._rts = False
        self._dtr = False
        self._rtscts = False
        self._dsrdtr = False
        _set_transport_timeout_ms(self._transport, 250)
        try:
            self._transport.setWriteTimeoutMs(1500)
        except Exception:
            pass

    def _apply_serial_parameters(self):
        setter = getattr(self._transport, "setSerialParameters", None)
        if callable(setter):
            setter(int(self._baudrate), int(self._bytesize),
                   float(self._stopbits), str(self._parity))
        else:
            # Backward compatibility with older PocketCHIRP transports.
            self._transport.setBaudRate(int(self._baudrate))

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        self._timeout = None if value is None else float(value)
        # PocketCHIRP transports are deadline based. Treat pyserial's None
        # (blocking forever) as a generous finite timeout rather than hanging
        # the Android worker thread indefinitely.
        ms = 30000 if self._timeout is None else max(1, int(self._timeout * 1000))
        _set_transport_timeout_ms(self._transport, ms)

    @property
    def write_timeout(self):
        return self._write_timeout

    @write_timeout.setter
    def write_timeout(self, value):
        self._write_timeout = None if value is None else float(value)
        ms = 30000 if self._write_timeout is None else max(1, int(self._write_timeout * 1000))
        setter = getattr(self._transport, "setWriteTimeoutMs", None)
        if callable(setter):
            setter(ms)

    @property
    def baudrate(self):
        return self._baudrate

    @baudrate.setter
    def baudrate(self, value):
        self._baudrate = int(value)
        self._apply_serial_parameters()

    @property
    def bytesize(self):
        return self._bytesize

    @bytesize.setter
    def bytesize(self, value):
        value = int(value)
        if value not in (5, 6, 7, 8):
            raise ValueError("Unsupported serial byte size: %r" % value)
        self._bytesize = value
        self._apply_serial_parameters()

    # Some older CHIRP drivers use ``databits`` rather than pyserial's
    # modern ``bytesize`` spelling. Keep both names backed by the exact same
    # framing state so the adapter does not need driver-specific exceptions.
    @property
    def databits(self):
        return self.bytesize

    @databits.setter
    def databits(self, value):
        self.bytesize = value

    @property
    def parity(self):
        return self._parity

    @parity.setter
    def parity(self, value):
        value = str(value or "N").upper()
        if value not in ("N", "E", "O", "M", "S"):
            raise ValueError("Unsupported serial parity: %r" % value)
        self._parity = value
        self._apply_serial_parameters()

    @property
    def stopbits(self):
        return self._stopbits

    @stopbits.setter
    def stopbits(self, value):
        value = float(value)
        if value not in (1.0, 1.5, 2.0):
            raise ValueError("Unsupported serial stop bits: %r" % value)
        self._stopbits = int(value) if value in (1.0, 2.0) else value
        self._apply_serial_parameters()

    @property
    def rts(self):
        return self._rts

    @rts.setter
    def rts(self, value):
        self._rts = bool(value)
        self._transport.setRts(self._rts)

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, value):
        self._dtr = bool(value)
        self._transport.setDtr(self._dtr)

    @property
    def rtscts(self):
        return self._rtscts

    @rtscts.setter
    def rtscts(self, value):
        # =====================================================================
        # POCKETCHIRP REAL RTS/CTS FLOW CONTROL - WEBCHIRP IMPROVEMENT #4
        # =====================================================================
        # CHIRP drivers use pyserial's ``pipe.rtscts`` flag when the radio
        # expects hardware RTS/CTS flow control.
        #
        # New behavior:
        #   USB serial -> ask MainActivity/usb-serial-for-android to enable the
        #   adapter's native FlowControl.RTS_CTS mode, but ONLY when the adapter
        #   explicitly advertises support.
        #
        # Compatibility fallback:
        #   If this Java capability is absent or unsupported, preserve the
        #   historical PocketCHIRP behavior exactly: asserting RTS when
        #   ``rtscts=True``. BLE/native USB therefore remain unchanged.
        #
        # EASY REVERT:
        #   Restore the old four-line setter which only assigned _rtscts and
        #   called ``self.rts = True`` when enabled.
        # =====================================================================
        self._rtscts = bool(value)

        native_applied = False
        setter = getattr(self._transport, "setRtsCtsFlowControl", None)
        if callable(setter):
            try:
                native_applied = bool(setter(self._rtscts))
            except Exception:
                # Fail safely back to the proven historical behavior.
                native_applied = False

        if self._rtscts and not native_applied:
            self.rts = True

    @property
    def dsrdtr(self):
        return self._dsrdtr

    @dsrdtr.setter
    def dsrdtr(self, value):
        # Likewise, expose the pyserial attribute even though Android's USB
        # serial API has no automatic DSR/DTR flow-control mode.
        self._dsrdtr = bool(value)
        if self._dsrdtr:
            self.dtr = True

    @property
    def in_waiting(self):
        getter = getattr(self._transport, "availableBytes", None)
        if not callable(getter):
            return 0
        return max(0, int(getter()))

    def inWaiting(self):
        """Legacy pyserial spelling still used by several CHIRP drivers."""
        return self.in_waiting

    # Very old pyserial method spellings retained by CHIRP's serial test shim.
    def setBaudrate(self, rate):
        self.baudrate = rate

    def setTimeout(self, timeout):
        self.timeout = timeout

    def setParity(self, parity):
        self.parity = parity

    def setRTS(self, level=True):
        """Legacy pyserial API; omitted level means assert RTS."""
        self.rts = level

    def setDTR(self, level=True):
        """Legacy pyserial API; omitted level means assert DTR."""
        self.dtr = level

    def isOpen(self):
        """pyserial 2.x compatibility alias."""
        return bool(self.is_open)

    def open(self):
        # The Android transport is physically opened by the proprietary app
        # before it is handed across IPC. This mirrors pyserial's state API
        # without trying to take transport ownership inside the GPL engine.
        self.is_open = True
        return None

    def read(self, size=1):
        # Universal READ rule: pass through the bytes the radio actually supplied.
        # No generic length/content rejection belongs in this transport wrapper.
        size = int(size)
        if size <= 0:
            return b""

        # pyserial timeout=0 means a genuinely non-blocking read: return only
        # bytes which are already queued. Android transports require a finite
        # millisecond timeout internally, so preserve the semantic distinction
        # here instead of turning zero into an accidental 1 ms blocking read.
        if self._timeout == 0:
            getter = getattr(self._transport, "availableBytes", None)
            if not callable(getter):
                return b""
            available = max(0, int(getter()))
            if available <= 0:
                return b""
            return bytes(self._transport.readBytes(min(size, available)))

        return bytes(self._transport.readBytes(size))

    def readline(self, size=-1):
        limit = int(size) if size is not None else -1
        out = bytearray()
        while limit < 0 or len(out) < limit:
            ch = self.read(1)
            if not ch:
                break
            out.extend(ch)
            if ch == b"\n":
                break
        return bytes(out)

    def read_until(self, expected=b"\n", size=None):
        expected = bytes(expected or b"\n")
        limit = None if size is None else int(size)
        out = bytearray()
        while limit is None or len(out) < limit:
            ch = self.read(1)
            if not ch:
                break
            out.extend(ch)
            if expected and out.endswith(expected):
                break
        return bytes(out)

    def write(self, data):
        raw = bytes(data)
        return int(self._transport.writeBytes(raw))

    def reset_input_buffer(self):
        try:
            clear = getattr(self._transport, "clearInputBuffer", None)
            if callable(clear):
                clear()
        except Exception:
            pass

    def reset_output_buffer(self):
        try:
            clear = getattr(self._transport, "clearOutputBuffer", None)
            if callable(clear):
                clear()
        except Exception:
            pass

    # pyserial 2.x compatibility aliases which still appear in older drivers.
    flushInput = reset_input_buffer
    flushOutput = reset_output_buffer

    def log(self, message):
        try:
            import logging as _logging
            _logging.getLogger("PocketCHIRP.serial").debug("%s", message)
        except Exception:
            pass
        # Never turn BLE per-block diagnostics into UI progress callbacks.
        # CHIRP drivers commonly pipe.log() inside the clone hot loop. Sending
        # those lines over Python->Java as progress=(0,0) adds synchronous IPC
        # between radio transactions and can make the progress bar disappear.
        #
        # The diagnostic is still emitted to Python logging above. USB behavior
        # is otherwise unchanged; BLE transport/profile diagnostics that matter
        # operationally are emitted explicitly by MainActivity.
        return None

    def flush(self):
        try:
            flush = getattr(self._transport, "flushOutput", None)
            if callable(flush):
                flush()
        except Exception:
            pass
        return None

    def close(self):
        self.is_open = False
        return None



class LegacyAndroidSerialPipe:
    """Exact pre-generalization serial contract used by proven Icom clone reads."""

    def __init__(self, java_transport):
        self._transport = java_transport
        self._timeout = 1.5
        self._baudrate = 9600
        self._rts = False
        self._dtr = False
        _set_transport_timeout_ms(self._transport, 1500)

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        self._timeout = float(value)
        _set_transport_timeout_ms(self._transport, max(1, int(self._timeout * 1000)))

    @property
    def baudrate(self):
        return self._baudrate

    @baudrate.setter
    def baudrate(self, value):
        self._baudrate = int(value)
        self._transport.setBaudRate(self._baudrate)

    @property
    def rts(self):
        return self._rts

    @rts.setter
    def rts(self, value):
        self._rts = bool(value)
        self._transport.setRts(self._rts)

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, value):
        self._dtr = bool(value)
        self._transport.setDtr(self._dtr)

    def read(self, size=1):
        return bytes(self._transport.readBytes(int(size)))

    def write(self, data):
        raw = bytes(data)
        return int(self._transport.writeBytes(raw))

    def reset_input_buffer(self):
        try:
            clear = getattr(self._transport, "clearInputBuffer", None)
            if callable(clear):
                clear()
        except Exception:
            pass

    flushInput = reset_input_buffer

    def reset_output_buffer(self):
        return None

    flushOutput = reset_output_buffer

    def flush(self):
        return None

    def close(self):
        return None


class AndroidNativeUsbDevice:
    """PyUSB/libusb-like façade over PocketCHIRP's Android USB bulk transport.

    The public GD-73A driver already contains the proven C7000 packet protocol.
    This adapter changes only the physical USB I/O backend: endpoint-aware
    read/write calls are forwarded to Android UsbDeviceConnection.bulkTransfer.
    """
    _is_libusb0 = True

    def __init__(self, java_transport):
        self._transport = java_transport

    def write(self, endpoint, data, timeout=None):
        if int(endpoint) & 0x80:
            raise IOError("Android native USB bulk write requires an OUT endpoint")
        if timeout is not None:
            try:
                self._transport.setWriteTimeoutMs(max(1, int(timeout)))
            except Exception:
                pass
        return int(self._transport.writeBytes(bytes(data)))

    def read(self, endpoint, size, timeout=None):
        if not (int(endpoint) & 0x80):
            raise IOError("Android native USB bulk read requires an IN endpoint")
        if timeout is not None:
            try:
                _set_transport_timeout_ms(self._transport, max(1, int(timeout)))
            except Exception:
                pass
        return bytes(self._transport.readBytes(int(size)))

    def close(self):
        # PocketCHIRP owns the physical Android USB connection lifecycle.
        # CHIRP may close its PyUSB-like handle, but the GPL engine must not
        # reach across Binder to tear down the proprietary app's transport.
        # This intentionally matches AndroidSerialPipe.close(): release of the
        # concrete UsbDeviceConnection happens when PocketCHIRP closes/recycles
        # the clone session.
        return None


def _is_native_usb_bulk_transport(java_transport):
    try:
        fn = getattr(java_transport, "isNativeUsbBulkTransport", None)
        return bool(fn()) if callable(fn) else False
    except Exception:
        return False


def _native_usb_identity(java_transport):
    """Return optional physical USB ID facts; never use them as a hard allow-list."""
    try:
        vid = int(java_transport.getNativeUsbVendorId())
        pid = int(java_transport.getNativeUsbProductId())
        return vid, pid
    except Exception:
        return -1, -1


def _native_usb_transport_kind(java_transport):
    """Classify the app-selected native USB transport using existing neutral facts.

    Bulk remains explicit in the v6 Binder contract. A non-bulk transport which
    nevertheless reports a physical USB VID/PID is the app-side FE/01/02 DFU
    transport. Ordinary serial/BLE transports report -1/-1 here.
    """
    if java_transport is None:
        return ""
    if _is_native_usb_bulk_transport(java_transport):
        return "bulk"
    vid, pid = _native_usb_identity(java_transport)
    return "dfu" if vid >= 0 and pid >= 0 else ""


def selected_native_usb_driver_facts_json():
    """Neutral native-USB capability contract for the currently selected driver."""
    cls = _selected_class()
    preferred = []
    for item in (getattr(cls, "POCKETCHIRP_USB_PREFERRED_IDS", ()) or ()):
        try:
            preferred.append({"vid": int(item[0]), "pid": int(item[1])})
        except Exception:
            continue
    transport = str(getattr(cls, "POCKETCHIRP_USB_TRANSPORT", "") or "").strip().casefold()
    if transport not in ("bulk", "dfu"):
        transport = ""
    return _json.dumps({
        "schemaVersion": 1,
        "vendor": str(getattr(cls, "VENDOR", "") or ""),
        "model": str(getattr(cls, "MODEL", "") or ""),
        "variant": str(getattr(cls, "VARIANT", "") or ""),
        "transport": transport,
        "preferredIds": preferred,
    }, separators=(",", ":"))


def _driver_usb_preferred_ids(cls):
    out = []
    for item in (getattr(cls, "POCKETCHIRP_USB_PREFERRED_IDS", ()) or ()):
        try:
            out.append((int(item[0]), int(item[1])))
        except Exception:
            continue
    return tuple(out)


def _dfu_frame(java_transport, direction, request, value=0,
               data=b"", length=None, timeout_ms=5000):
    """Execute one standard DFU class-interface request through the v6 byte IPC.

    The proprietary app validates/claims an FE/01/02 interface and interprets
    this private frame. The GPL side keeps all DfuSe/radio command sequencing.
    """
    import struct as _pc_struct
    direction = int(direction)
    request = int(request) & 0xFF
    value = int(value) & 0xFFFF
    payload = bytes(data or b"")
    if length is None:
        length = len(payload)
    length = int(length)
    if length < 0 or length > 65536:
        raise IOError("DFU control length is outside PocketCHIRP bounds")
    if direction == 0 and len(payload) != length:
        raise IOError("DFU OUT payload length mismatch")
    if direction == 1 and payload:
        raise IOError("DFU IN request cannot carry an OUT payload")

    # P C D F | version | direction | request | value:u16 | length:u32 | timeout:u32
    frame = (b"PCDF" + bytes((1, direction, request))
             + _pc_struct.pack("<HII", value, length,
                               max(1, min(60000, int(timeout_ms)))))
    java_transport.writeBytes(frame + (payload if direction == 0 else b""))
    if direction == 0:
        return b""
    # Transport policy: return exactly what Android says the device returned.
    # Do not interpret radio response length/content here.  USB control-IN
    # wLength is a maximum, and protocol-specific validation/retry belongs to
    # the selected radio driver.
    return bytes(java_transport.readBytes(length))


def _install_android_dfu_factory(cls, java_transport):
    """Inject Android control-transfer I/O into a driver's native DFU backend.

    This intentionally works with both newer PocketCHIRP-aware drivers and older
    native DfuSe drivers.  A driver does not need an Android-specific factory hook:
    if it exposes its native DFU backend class, PocketCHIRP can instantiate that
    class without running the OS-specific constructor and replace _open_native_dfu
    for this Android runtime only.
    """
    import types as _pc_types
    module = sys.modules.get(getattr(cls, "__module__", ""))
    if module is None:
        raise ValueError("Selected DFU driver module is not loaded.")

    backend_name = str(getattr(
        cls, "POCKETCHIRP_DFU_BACKEND_CLASS", "_NativeSTTubDFU") or
        "_NativeSTTubDFU")
    native_cls = getattr(module, backend_name, None)
    if native_cls is None:
        raise ValueError(
            "Selected DFU driver does not expose a usable native DFU backend.")

    def factory():
        # Skip the backend's OS-specific constructor (for example Windows
        # STTub30), but retain every driver-owned high-level DFU/radio method.
        dev = object.__new__(native_cls)

        def android_control(self, direction, request, value=0, index=0,
                            data=b"", length=None):
            # Driver direction constants use 0=OUT, 1=IN. Interface selection is
            # app-owned; the supplied index cannot redirect to another interface.
            return _dfu_frame(
                java_transport, int(direction), int(request), int(value),
                data=data, length=length, timeout_ms=5000)

        def android_close(self):
            # PocketCHIRP owns the physical UsbDeviceConnection lifecycle.
            return None

        dev._control = _pc_types.MethodType(android_control, dev)
        dev.close = _pc_types.MethodType(android_close, dev)
        return dev

    # Newer drivers may consult this hook themselves.
    setattr(module, "_POCKETCHIRP_ANDROID_DFU_FACTORY", factory)

    # Older native DfuSe drivers often have _open_native_dfu() which directly
    # constructs the Windows backend. Replace it for this Android runtime so they
    # gain Android DFU support without requiring a source-level radio patch.
    setattr(module, "_open_native_dfu", factory)


def _infer_native_usb_transport_from_driver(cls):
    """Infer a native USB family from concrete driver backend capabilities.

    Explicit POCKETCHIRP_USB_TRANSPORT remains authoritative. Structural inference
    is only used when that declaration is absent.
    """
    module = sys.modules.get(getattr(cls, "__module__", ""))

    # Native DfuSe/ST DFU backend: class exists in the selected driver's module.
    backend_name = str(getattr(
        cls, "POCKETCHIRP_DFU_BACKEND_CLASS", "_NativeSTTubDFU") or
        "_NativeSTTubDFU")
    if module is not None and isinstance(getattr(module, backend_name, None), type):
        return "dfu"

    # Native bulk drivers conventionally expose an instance _open_usb hook.
    if callable(getattr(cls, "_open_usb", None)):
        return "bulk"

    return ""

def _prepare_native_usb_class_adapter(cls, pipe):
    """Bind a driver-declared native-USB transport to Android by capability.

    The app selects USB_SERIAL/BULK/DFU from Android interface descriptors.
    The CHIRP driver must explicitly declare the native family it accepts.
    VID/PID values are optional confidence hints only; the driver's own protocol
    identity checks remain authoritative.
    """
    java_transport = getattr(pipe, "_transport", None)
    kind = _native_usb_transport_kind(java_transport)
    if not kind:
        return

    declared = str(getattr(cls, "POCKETCHIRP_USB_TRANSPORT", "") or "").strip().casefold()
    effective = declared
    inferred = False
    if not effective:
        effective = _infer_native_usb_transport_from_driver(cls)
        inferred = bool(effective)
        if inferred:
            _transport_note(
                pipe,
                "NATIVE USB: selected driver has no explicit PocketCHIRP USB declaration; "
                "inferred %s from its native backend capabilities." % effective.upper())

    # An explicit declaration is authoritative. Structural inference is only a
    # compatibility fallback for drivers which predate the declaration contract.
    if effective != kind:
        if declared:
            reason = "declares %s" % declared.upper()
        elif effective:
            reason = "exposes a %s backend" % effective.upper()
        else:
            reason = "does not expose a compatible native USB backend"
        raise ValueError(
            "Attached radio exposes USB %s, but selected driver %s %s %s. "
            "No radio commands were sent." %
            (kind.upper(), getattr(cls, "VENDOR", ""), getattr(cls, "MODEL", ""), reason))

    vid, pid = _native_usb_identity(java_transport)
    preferred = _driver_usb_preferred_ids(cls)
    if preferred and (vid, pid) not in preferred:
        _transport_note(
            pipe,
            "NATIVE USB: device %04X:%04X is not in the driver's preferred-ID "
            "hints; continuing because interface capability matches %s. Driver "
            "protocol identity checks remain authoritative." %
            (vid, pid, kind.upper()))

    if kind == "bulk":
        if not hasattr(cls, "_open_usb"):
            raise ValueError(
                "Selected native-bulk driver does not expose its USB backend hook.")
        def _android_open_usb(self):
            return AndroidNativeUsbDevice(java_transport)
        cls._open_usb = _android_open_usb
        return

    if kind == "dfu":
        _install_android_dfu_factory(cls, java_transport)
        return

    raise ValueError("Unsupported native USB transport family %r" % kind)


def _uses_legacy_icom_pipe(cls):
    """True only for CHIRP's Icom clone-mode family (not Icom live mode)."""
    try:
        from chirp.drivers import icf
        return issubclass(cls, icf.IcomCloneModeRadio)
    except Exception:
        return False


def _pipe_for_class(cls, java_transport):
    if _uses_legacy_icom_pipe(cls):
        return LegacyAndroidSerialPipe(java_transport)
    return AndroidSerialPipe(java_transport)

def _apply_driver_serial_open_contract(cls, pipe):
    """Apply CHIRP's exact driver-declared USB serial control-line contract.

    HARD REGRESSION GUARD -- never replace this with blanket RTS/DTR values.
    Some interfaces require asserted DTR/RTS for level-converter power or
    handshaking, while other drivers intentionally request RTS low (notably
    Icom CI-V, where an interface may use RTS as PTT). BLE is untouched.
    """
    if getattr(pipe, "is_ble", False):
        return
    wants_dtr = bool(getattr(cls, "WANTS_DTR", True))
    wants_rts = bool(getattr(cls, "WANTS_RTS", True))
    hardware_flow = bool(getattr(cls, "HARDWARE_FLOW", False))
    try:
        pipe.rtscts = hardware_flow
    except Exception:
        pass
    try:
        pipe.rts = wants_rts
    except Exception:
        pass
    try:
        pipe.dtr = wants_dtr
    except Exception:
        pass
    _transport_note(
        pipe,
        "CHIRP SERIAL OPEN CONTRACT: DTR=%s RTS=%s RTS/CTS=%s" %
        (wants_dtr, wants_rts, hardware_flow))


def _prepare_clone_pipe(cls, java_transport):
    """Open the Android transport with the same serial contract CHIRP uses.

    The proprietary app owns only the physical Android transport. The GPL
    engine owns CHIRP's serial parameters and clone lifecycle. In particular,
    do not perform a blanket RX purge here: desktop CHIRP opens the port, sets
    its driver-declared controls/baud/timeout, then lets detect_from_serial()
    and sync_in()/sync_out() own every protocol byte.
    """
    pipe = _pipe_for_class(cls, java_transport)
    pipe.timeout = 0.25
    if hasattr(pipe, "write_timeout"):
        pipe.write_timeout = 1.5
    if not getattr(pipe, "is_ble", False):
        pipe.baudrate = int(getattr(cls, "BAUD_RATE", 9600) or 9600)
        _apply_driver_serial_open_contract(cls, pipe)
    return pipe



def _transport_note(pipe, message):
    """Surface CHIRP adapter/protocol notes in PocketCHIRP's log when possible."""
    try:
        cb = getattr(pipe._transport, "onChirpProgress", None)
        if callable(cb):
            cb(str(message), 0, 0)
    except Exception:
        pass


def _configure_pipe_for_driver(cls, pipe):
    """Apply CHIRP's serial-open defaults without touching protocol bytes."""
    pipe.baudrate = int(getattr(cls, "BAUD_RATE", 9600) or 9600)
    pipe.timeout = 0.25
    if hasattr(pipe, "write_timeout"):
        pipe.write_timeout = 1.5
    if not getattr(pipe, "is_ble", False):
        _apply_driver_serial_open_contract(cls, pipe)


# =============================================================================
# CHIRP-SIDE BLE FACTS / ONE-ATTEMPT CLONE ADAPTER
# =============================================================================
# PocketCHIRP's Android BLE resolver policy lives in proprietary Java.  This
# engine exposes only facts derived from the selected CHIRP class and a single
# sync_in attempt. Candidate ordering, direct/external role, write mode, MTU,
# retries and resolver resets must NOT be reintroduced here.
# =============================================================================
def selected_serial_driver_facts_json():
    """Return the exact selected CHIRP driver's small serial-open fact contract."""
    from chirp import chirp_common
    cls = _selected_class()
    return _json.dumps({
        "schemaVersion": 1,
        "vendor": str(getattr(cls, "VENDOR", "") or "").strip(),
        "model": str(getattr(cls, "MODEL", "") or "").strip(),
        "variant": str(getattr(cls, "VARIANT", "") or "").strip(),
        "className": str(getattr(cls, "__name__", "") or ""),
        "moduleName": str(getattr(cls, "__module__", "") or ""),
        "baudRate": int(getattr(cls, "BAUD_RATE", 9600) or 9600),
        "wantsDtr": bool(getattr(cls, "WANTS_DTR", True)),
        "wantsRts": bool(getattr(cls, "WANTS_RTS", True)),
        "hardwareFlow": bool(getattr(cls, "HARDWARE_FLOW", False)),
        "cloneMode": bool(issubclass(cls, chirp_common.CloneModeRadio)),
        "liveRadio": bool(issubclass(cls, chirp_common.LiveRadio)),
    }, separators=(",", ":"))


def selected_ble_driver_facts_json():
    """Return raw neutral facts from the currently selected CHIRP class."""
    from chirp import chirp_common
    cls = _selected_class()
    return _json.dumps({
        "schemaVersion": 1,
        "vendor": str(getattr(cls, "VENDOR", "") or "").strip(),
        "model": str(getattr(cls, "MODEL", "") or "").strip(),
        "variant": str(getattr(cls, "VARIANT", "") or "").strip(),
        "className": str(getattr(cls, "__name__", "") or ""),
        "moduleName": str(getattr(cls, "__module__", "") or ""),
        "baudRate": int(getattr(cls, "BAUD_RATE", 9600) or 9600),
        "cloneMode": bool(issubclass(cls, chirp_common.CloneModeRadio)),
        "liveRadio": bool(issubclass(cls, chirp_common.LiveRadio)),
    }, separators=(",", ":"))


def _unwrap_runtime_class(cls):
    """Return the registered CHIRP implementation behind a dynamic alias."""
    seen = set()
    current = cls
    while isinstance(current, type) and current not in seen:
        seen.add(current)
        original = getattr(current, "_orig_rclass", None)
        if not isinstance(original, type) or original is current:
            break
        current = original
    return current


def _detected_manager_class(cls):
    """Return CHIRP's visible manager for a detected-only runtime class."""
    current = _unwrap_runtime_class(cls)
    manager = getattr(current, "_DETECTED_BY", None)
    return manager if isinstance(manager, type) else None


def _detect_selected_clone_class(selected_cls, pipe):
    """Run CHIRP's native serial detector exactly where desktop CHIRP does.

    A visible manager may return a registered detected-only subclass. Those
    subclasses are intentionally hidden from the chooser but are the classes
    which must perform sync_in(), be saved in image metadata, and later perform
    sync_out().
    """
    # Desktop CHIRP's dynamic marketed aliases execute the registered parent
    # implementation. Use that parent for detection so detected_models() sees
    # the manager's registered DETECTED_MODELS_<ClassName> list.
    detector_cls = _unwrap_runtime_class(selected_cls)
    detector = getattr(detector_cls, "detect_from_serial", None)
    if not callable(detector):
        return selected_cls

    try:
        detected_cls = detector(pipe)
    except NotImplementedError:
        return selected_cls

    if not isinstance(detected_cls, type):
        raise ValueError("CHIRP detect_from_serial() did not return a radio class")

    # Keep the exact public alias only when CHIRP found no different runtime
    # class. If a manager selected a detected-only subclass, use that subclass
    # exactly; this is CHIRP's normal lifecycle.
    if detected_cls is detector_cls:
        return selected_cls

    manager = _detected_manager_class(detected_cls)
    if manager is not None and manager is not detector_cls:
        raise ValueError(
            "CHIRP detector returned a model outside the selected manager family: "
            "%s -> %s" % (detector_cls.__name__, detected_cls.__name__))

    _transport_note(
        pipe,
        "CHIRP detected runtime driver: %s.%s (%s %s%s)" % (
            getattr(detected_cls, "__module__", "?"),
            getattr(detected_cls, "__name__", "?"),
            str(getattr(detected_cls, "VENDOR", "") or ""),
            str(getattr(detected_cls, "MODEL", "") or ""),
            (" [%s]" % getattr(detected_cls, "VARIANT", ""))
            if getattr(detected_cls, "VARIANT", "") else "",
        ))
    return detected_cls



# =============================================================================
# CENTRAL NATIVE/DIRECT-BLE PROTOCOL CAPABILITIES
# =============================================================================
# Generic BLE transport policy belongs in proprietary Android. This table is
# deliberately small and engine-side: it records only CHIRP/radio protocol facts
# which are not expressible by the stock driver today.
#
# IMPORTANT:
# - No replacement/forked CHIRP driver files are required.
# - Ordinary serial transports never use these native-BLE overrides.
# - Add an entry only after an OEM app / radio trace proves the protocol fact.
# =============================================================================
_DIRECT_BLE_CAPABILITIES = {
    ("baofeng", "uv-5r mini", ""): {
        # Ola Radio direct-BLE HCI trace: Mini download requests 0x80-byte
        # protocol blocks. Stock CHIRP already uses 0x80 for BLE upload.
        "download_adapter": "baofeng_uv17pro_framed",
        "download_block_size": 0x80,
    },
}


def _direct_ble_capability_for_radio(radio):
    key = (
        str(getattr(radio, "VENDOR", "") or "").strip().casefold(),
        str(getattr(radio, "MODEL", "") or "").strip().casefold(),
        str(getattr(radio, "VARIANT", "") or "").strip().casefold(),
    )
    return _DIRECT_BLE_CAPABILITIES.get(key)


def _direct_ble_baofeng_uv17pro_download(radio):
    """Central 0x80-capable framed download adapter for the UV17Pro family."""
    from chirp import chirp_common

    capability = getattr(radio, "_pocketchirp_direct_ble_capability", None) or {}
    block_size = int(capability.get("download_block_size", 0) or 0)
    if block_size <= 0:
        raise RuntimeError("Direct-BLE download capability has no block size")

    impl_cls = _unwrap_runtime_class(radio.__class__)
    module_name = str(getattr(impl_cls, "__module__", "") or "")
    module = sys.modules.get(module_name)
    if module is None:
        module = __import__(module_name, fromlist=["*"])

    do_ident = getattr(module, "_do_ident", None)
    bfc = getattr(module, "bfc", None)
    crypt = getattr(module, "_crypt", None)
    if not callable(do_ident) or bfc is None:
        raise RuntimeError(
            "Direct-BLE framed adapter is incompatible with %s" % module_name)

    do_ident(radio)

    data = b""
    status = chirp_common.Status()
    status.cur = 0
    status.max = sum(
        (int(size) + block_size - 1) // block_size
        for size in radio.MEM_SIZES)
    status.msg = "Cloning from radio on BLE..."
    radio.status_fn(status)

    completed = 0
    for mem_start, mem_size in zip(radio.MEM_STARTS, radio.MEM_SIZES):
        mem_start = int(mem_start)
        mem_size = int(mem_size)
        mem_end = mem_start + mem_size

        for addr in range(mem_start, mem_end, block_size):
            # Some Mini regions end on a 0x40 tail. The OEM BLE protocol still
            # returns one full 0x80 block; append only the logical region bytes.
            byte_count = min(block_size, mem_end - addr)
            frame = radio._make_read_frame(addr, block_size)

            bfc._rawsend(radio, frame)
            block = bfc._rawrecv(radio, block_size + 4)

            if bool(getattr(radio, "_uses_encr", False)):
                if not callable(crypt):
                    raise RuntimeError(
                        "Encrypted direct-BLE framed adapter has no _crypt helper")
                block = crypt(radio._encrsym, block[4:])
            else:
                block = block[4:]

            data += block[:byte_count]
            completed += 1
            status.cur = completed
            radio.status_fn(status)

    return data


def _apply_direct_ble_protocol_capabilities(radio, pipe):
    """Apply proven protocol facts to one native/direct-BLE radio instance."""
    if not bool(getattr(pipe, "is_direct_ble", False)):
        return None

    capability = _direct_ble_capability_for_radio(radio)
    if not capability:
        return None

    adapter = str(capability.get("download_adapter", "") or "")
    if adapter == "baofeng_uv17pro_framed":
        import types as _pc_types
        radio._pocketchirp_direct_ble_capability = dict(capability)
        radio.download_function = _pc_types.MethodType(
            _direct_ble_baofeng_uv17pro_download, radio)
    elif adapter:
        raise RuntimeError("Unknown direct-BLE download adapter: " + adapter)

    return capability



class _PocketChirpUv82x3BleUv5rTimeProxy:
    """Module-local time proxy for the exact UV-82X3 CHIRP BLE READ path.

    CHIRP's uv5r._read_block() deliberately sleeps 50 ms after each host ACK.
    PocketCHIRP owns BLE serialization/pacing. This experiment
    shortens only that exact 0.050-second CHIRP settle to 5 ms, only for the
    Radioddity UV-82X3 over BLE.

    USB and writes are untouched. Every other sleep duration is delegated.
    """

    def __init__(self, real_time):
        self._real_time = real_time

    def sleep(self, seconds):
        try:
            value = float(seconds)
        except Exception:
            return self._real_time.sleep(seconds)

        if abs(value - 0.050) < 0.000001:
            return self._real_time.sleep(0.005)
        return self._real_time.sleep(seconds)

    def __getattr__(self, name):
        return getattr(self._real_time, name)


def _is_exact_uv82x3_radio(radio):
    impl_cls = _unwrap_runtime_class(radio.__class__)
    return (
        str(getattr(radio, "VENDOR", "") or "").strip().casefold() == "radioddity"
        and str(getattr(radio, "MODEL", "") or "").strip().casefold() == "uv-82x3"
        and str(getattr(impl_cls, "__module__", "") or "").strip().casefold().endswith(".uv5r")
        and str(getattr(impl_cls, "__name__", "") or "") == "Radioddity82X3Radio"
    )


def _sync_in_with_transport_read_capabilities(
        radio, pipe, physical_transport_kind="unknown"):
    """Run sync_in with temporary, fail-restored protocol timing capability.

    CHIRP-facing BLE semantics are intentionally normalized by proprietary
    PocketCHIRP before Binder. An external BLE-to-serial programmer therefore
    looks like ordinary serial here, which is correct for CHIRP framing.

    The already-existing neutral physical transport kind is carried separately
    only so exact radio-protocol timing accommodations can distinguish a physical
    BLE hop from USB without learning anything about adapter brands/profiles.
    """
    physical_ble = (
        str(physical_transport_kind or "").strip().casefold() == "ble")
    if not physical_ble or not _is_exact_uv82x3_radio(radio):
        radio.sync_in()
        return

    # This is the one part which must remain engine-side because CHIRP itself
    # owns the 50 ms sleep. The UV-82X3 uses chirp.drivers.uv5r._read_block(),
    # whose module-local `time.sleep(0.05)` runs after every host ACK.
    # Keep it exact-radio + physical-BLE + READ only.
    # No programmer/device/profile identity is used or exposed here.
    from chirp.drivers import uv5r as _pc_uv5r

    original_time = getattr(_pc_uv5r, "time", None)
    if original_time is None or not hasattr(original_time, "sleep"):
        radio.sync_in()
        return

    _pc_uv5r.time = _PocketChirpUv82x3BleUv5rTimeProxy(original_time)
    try:
        radio.sync_in()
    finally:
        _pc_uv5r.time = original_time


def _sync_in_once(cls, pipe, java_transport,
                  physical_transport_kind="unknown"):
    """Run one CHIRP clone download using CHIRP's native class lifecycle."""
    detected_cls = _detect_selected_clone_class(cls, pipe)
    _prepare_native_usb_class_adapter(detected_cls, pipe)
    radio = detected_cls(pipe)
    _apply_direct_ble_protocol_capabilities(radio, pipe)
    _status_callback(radio, java_transport)
    _sync_in_with_transport_read_capabilities(
        radio, pipe, physical_transport_kind)
    return radio

# =============================================================================
# CHIRP-SIDE WRITE REQUIREMENT CHECK ONLY
# =============================================================================
# Android BLE profile selection is proprietary PocketCHIRP policy. The engine
# may enforce CHIRP/radio-protocol requirements after the app reports neutral
# transport facts (for example the ATT payload observed after its MTU request).
# =============================================================================
def _enforce_ble_write_requirements(cls, pipe, radio, transport_context_json=None):
    if not getattr(pipe, "is_ble", False):
        return
    try:
        context = _json.loads(str(transport_context_json or "{}"))
        if not isinstance(context, dict):
            context = {}
    except Exception:
        context = {}

    vendor = str(getattr(cls, "VENDOR", "") or "").strip().casefold()
    model = str(getattr(cls, "MODEL", "") or "").strip().casefold()
    # TD-H9's CHIRP-side upload block remains 0x20. PocketCHIRP owns how MTU is
    # negotiated; the engine only fails closed if the app reports an ATT payload
    # too small for the resulting 37-byte W frame.
    if vendor == "tidradio" and "td-h9" in model:
        radio.BLOCKSIZE_UP_BLE = 0x20
        mtu_payload = int(context.get("bleMtuPayload", 20) or 20)
        if mtu_payload < 37:
            raise RuntimeError(
                "TD-H9 BLE write requires ATT payload >=37; proprietary "
                "PocketCHIRP BLE policy reported payload %d" % mtu_payload)

# CHIRP's detectable-driver lifecycle is implemented in _detect_selected_clone_class().
# Do not reintroduce family-specific pre-identification hooks here; managers such
# as TD-H3/TD-H8 intentionally perform that handshake in detect_from_serial().







def _format_memory(mem):
    freq_mhz = mem.freq / 1_000_000.0
    name = (mem.name or "").strip()
    duplex = mem.duplex or "simplex"

    if mem.duplex in ("+", "-"):
        offset = f" {mem.offset / 1_000_000.0:.6f} MHz"
    elif mem.duplex == "split":
        offset = f" TX {mem.offset / 1_000_000.0:.6f}"
    elif mem.duplex == "off":
        offset = " TX-OFF"
    else:
        offset = ""

    tone = ""
    if mem.tmode == "Tone":
        tone = f" Tone {mem.rtone:g}"
    elif mem.tmode == "TSQL":
        tone = f" TSQL {mem.ctone:g}"
    elif mem.tmode in ("DTCS", "DTCS-R"):
        tone = f" {mem.tmode} {mem.dtcs:03d}"
    elif mem.tmode == "Cross":
        tone = f" Cross {mem.cross_mode}"

    power = f" {mem.power}" if mem.power is not None else ""
    mode = f" {mem.mode}" if mem.mode else ""

    return (
        f"{mem.number:>3}  {freq_mhz:10.6f}  "
        f"{name:<8}  {duplex}{offset}{tone}{mode}{power}"
    ).rstrip()



def _split_chirp_img(image_bytes):
    """Return (raw_payload, metadata_bytes_or_empty)."""
    from chirp import chirp_common
    magic = chirp_common.CloneModeRadio.MAGIC
    try:
        idx = image_bytes.index(magic)
    except ValueError:
        return image_bytes, b""
    return image_bytes[:idx], image_bytes[idx:]








# ---------------------------------------------------------------------------
# PocketCHIRP Stage 4 responsive editor API
# ---------------------------------------------------------------------------
import json as _json





# The production companion engine relies on CHIRP's own standard image metadata.
# PocketCHIRP-specific labels/history live in the proprietary application.

def _save_working_radio(radio):
    global _last_image_bytes, _last_raw_bytes, _last_hash_info

    # =====================================================================
    # POCKETCHIRP GENERIC LIVE-RADIO SNAPSHOT — ADDITIVE BRANCH ONLY
    # =====================================================================
    # A LiveRadio talks to hardware from get_memory()/set_memory(), so it must
    # never fall through the normal CloneModeRadio image-save path while the
    # user is editing.  The detached proxy below serializes only PocketCHIRP's
    # private snapshot container here.  Every existing CloneModeRadio reaches
    # the historical code below byte-for-byte unchanged.
    #
    # EASY REVERT: remove this guarded branch and the LiveRadio block near
    # download_selected_editor(). No CloneModeRadio transport/protocol code is
    # shared with the new path.
    # =====================================================================
    if getattr(radio, "_POCKETCHIRP_LIVE_SNAPSHOT_PROXY", False):
        _store_live_snapshot_as_working(radio._snapshot)
        return

    name = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tmp:
            name = tmp.name
        _stamp_custom_image_metadata(radio)
        radio.save(name)
        with open(name, "rb") as f:
            _last_image_bytes = f.read()
    finally:
        if name:
            try: os.unlink(name)
            except OSError: pass
    _last_raw_bytes, _ = _split_chirp_img(_last_image_bytes)
    raw_sha = hashlib.sha256(_last_raw_bytes).hexdigest()
    img_sha = hashlib.sha256(_last_image_bytes).hexdigest()
    _last_hash_info = f"Raw payload SHA-256: {raw_sha}\nFull .img SHA-256: {img_sha}"


def _safe_attr(obj, name, default=None):
    try:
        value = getattr(obj, name)
    except Exception:
        return default
    return default if value is None else value


def _safe_int(value, default=0):
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError, OverflowError):
        return default


def _memory_extra_dict(mem):
    """Serialize driver-specific per-memory RadioSetting values.

    CHIRP RadioSetting is a real class hierarchy: MemSetting and other
    subclasses are still settings, and one RadioSetting may contain multiple
    RadioSettingValue objects. Preserve those semantics instead of testing a
    literal class name or assuming every setting is scalar.
    """
    from chirp import settings as chirp_settings

    extra = _safe_attr(mem, "extra", None)
    if not extra:
        return []

    out = []
    seen_groups = set()

    def walk(group, group_label="Memory", group_path=()):
        oid = id(group)
        if oid in seen_groups:
            return
        seen_groups.add(oid)
        try:
            items = list(group)
        except Exception:
            return
        for index, item in enumerate(items):
            if isinstance(item, chirp_settings.RadioSetting):
                keys = list(item.keys())
                for component_index in keys:
                    try:
                        out.append(_setting_to_dict(
                            item,
                            group_label,
                            group_path=group_path,
                            component_index=int(component_index),
                            component_count=len(keys),
                        ))
                    except Exception:
                        continue
            elif isinstance(item, chirp_settings.RadioSettingGroup):
                walk(
                    item,
                    _setting_group_label(item, group_label),
                    group_path + (_setting_group_name(item, "group-%d" % index),),
                )

    walk(extra)
    return out

def _memory_dict(radio, n):
    """Serialize a CHIRP Memory while preserving native/special identity."""
    mem = radio.get_memory(n)
    native_number = _safe_attr(mem, "number", n)
    extd_number = str(_safe_attr(mem, "extd_number", "") or "")
    is_special = bool(extd_number) or isinstance(n, str)
    d = {
        "number": native_number if not isinstance(native_number, str) else n,
        "nativeNumber": native_number,
        "nativeKey": extd_number or n,
        "extdNumber": extd_number,
        "special": is_special,
        "memoryId": ("special:" + (extd_number or str(n))) if is_special
                    else ("number:" + str(native_number)),
        "empty": bool(_safe_attr(mem, "empty", False)),
        "immutable": list(_safe_attr(mem, "immutable", []) or []),
        # Some CHIRP drivers expose per-memory controls even on an unused slot.
        # Preserve them so creating a new channel does not discard driver-owned
        # options such as signaling/scrambler/scan behavior.
        "extra": _memory_extra_dict(mem),
    }
    if d["empty"]:
        return d

    power = _safe_attr(mem, "power", None)
    d.update({
        "name": str(_safe_attr(mem, "name", "") or "").strip(),
        "freq": _safe_float(_safe_attr(mem, "freq", 0), 0.0) / 1_000_000.0,
        "duplex": str(_safe_attr(mem, "duplex", "") or ""),
        "offset": _safe_float(_safe_attr(mem, "offset", 0), 0.0) / 1_000_000.0,
        "tmode": str(_safe_attr(mem, "tmode", "") or ""),
        "rtone": _safe_float(_safe_attr(mem, "rtone", None), 88.5),
        "ctone": _safe_float(_safe_attr(mem, "ctone", None), 88.5),
        "dtcs": _safe_int(_safe_attr(mem, "dtcs", None), 23),
        "rx_dtcs": _safe_int(_safe_attr(mem, "rx_dtcs", None), 23),
        "dtcs_polarity": str(_safe_attr(mem, "dtcs_polarity", "NN") or "NN"),
        "cross_mode": str(_safe_attr(mem, "cross_mode", "Tone->Tone") or "Tone->Tone"),
        "mode": str(_safe_attr(mem, "mode", "FM") or "FM"),
        "power": str(power) if power is not None else "",
        "powerDbm": (int(power) if power is not None else None),
        "skip": str(_safe_attr(mem, "skip", "") or ""),
        "tuning_step": _safe_float(_safe_attr(mem, "tuning_step", None), 0.0),
        "comment": str(_safe_attr(mem, "comment", "") or ""),
    })
    # Digital/D-STAR memories use these optional CHIRP fields. Do not invent
    # them on analog memories; emit only attributes the driver supplies.
    for field in ("dv_urcall", "dv_rpt1call", "dv_rpt2call", "dv_code"):
        if hasattr(mem, field):
            value = _safe_attr(mem, field, "")
            d[field] = _safe_int(value, 0) if field == "dv_code" else str(value or "")
    return d


def _setting_group_name(group, fallback="Settings"):
    """Return CHIRP's stable group name when available."""
    try:
        return str(group.get_name())
    except Exception:
        return str(fallback)


def _setting_group_label(group, fallback="Settings"):
    """Return CHIRP's human-readable group label when available."""
    try:
        return str(group.get_shortname())
    except Exception:
        try:
            return str(group.get_name())
        except Exception:
            return str(fallback)


def _setting_id(index_path, component_index=None):
    # Structural identity is intentionally based on CHIRP's actual nested tree,
    # not merely RadioSetting.get_name(). Multiple drivers legitimately reuse a
    # setting name in different groups. Multi-value RadioSetting objects append
    # a component suffix so each desktop-CHIRP value remains independently
    # editable without inventing a new setting name.
    base = "v1:" + "/".join(str(int(x)) for x in index_path)
    if component_index is not None:
        base += "#" + str(int(component_index))
    return base

def _walk_settings_tree(root):
    """Yield (RadioSetting, index_path, group_names, group_label) faithfully.

    Use CHIRP's type hierarchy, not literal class names. MemSetting and other
    RadioSetting subclasses are leaf settings even though they are iterable.
    The ancestry guard prevents a malformed/custom driver from creating an
    infinite settings cycle that can crash the neutral document serializer.
    """
    from chirp import settings as chirp_settings

    def walk(node, index_path=(), group_names=(), group_label="Settings",
             ancestors=frozenset()):
        oid = id(node)
        if oid in ancestors:
            return
        branch = ancestors | {oid}
        try:
            items = list(node)
        except Exception:
            return
        for index, item in enumerate(items):
            path = index_path + (index,)
            if isinstance(item, chirp_settings.RadioSetting):
                yield item, path, group_names, group_label
                continue
            if not isinstance(item, chirp_settings.RadioSettingGroup):
                continue
            child_name = _setting_group_name(item, "group-%d" % index)
            child_label = _setting_group_label(item, group_label)
            yield from walk(
                item,
                path,
                group_names + (child_name,),
                child_label,
                branch,
            )
    yield from walk(root)

def _resolve_setting(settings, setting_id=None, expected_name=None):
    """Resolve one exact CHIRP RadioSettingValue component.

    Returns (RadioSetting, component_index, RadioSettingValue). Current
    PocketCHIRP IDs use ``v1:path`` for scalar settings and ``v1:path#N`` for
    CHIRP multi-value settings. Legacy name lookup remains fail-closed.
    """
    sid = str(setting_id or "")
    component_index = None
    if sid.startswith("v1:"):
        body = sid[3:]
        if "#" in body:
            tail, component_text = body.rsplit("#", 1)
            try:
                component_index = int(component_text)
            except Exception as exc:
                raise ValueError("Invalid radio-setting component identity") from exc
        else:
            tail = body
        try:
            indexes = [int(x) for x in tail.split("/") if x != ""]
        except Exception as exc:
            raise ValueError("Invalid radio-setting identity") from exc
        if not indexes:
            raise ValueError("Invalid radio-setting identity")
        node = settings
        try:
            for index in indexes:
                node = list(node)[index]
        except Exception as exc:
            raise ValueError(
                "Radio setting moved or is no longer available; reload the image") from exc
        from chirp import settings as chirp_settings
        if not isinstance(node, chirp_settings.RadioSetting):
            raise ValueError(
                "Radio-setting identity no longer points to a setting; reload the image")
        if expected_name is not None and str(node.get_name()) != str(expected_name):
            raise ValueError(
                "Radio setting changed identity; reload the image before editing")
        keys = [int(x) for x in node.keys()]
        if component_index is None:
            if len(keys) != 1:
                raise ValueError(
                    "This radio setting contains multiple values. Reload with the current PocketCHIRP editor.")
            component_index = keys[0]
        if component_index not in keys:
            raise ValueError(
                "Radio-setting component moved or is no longer available; reload the image")
        return node, component_index, node[component_index]

    # Backward compatibility for an older editor. Never silently choose the
    # first duplicate or the first value of a multi-value setting.
    matches = []
    for item, *_ in _walk_settings_tree(settings):
        if str(item.get_name()) == str(expected_name):
            matches.append(item)
    if not matches:
        raise ValueError("Setting not found: " + str(expected_name))
    if len(matches) != 1:
        raise ValueError(
            "This driver has multiple settings named %s. Reload with the current PocketCHIRP editor."
            % expected_name)
    found = matches[0]
    keys = [int(x) for x in found.keys()]
    if len(keys) != 1:
        raise ValueError(
            "This radio setting contains multiple values. Reload with the current PocketCHIRP editor.")
    component_index = keys[0]
    return found, component_index, found[component_index]

def _setting_value_for_ui(value):
    """Return a neutral scalar for one CHIRP RadioSettingValue.

    Desktop CHIRP can display an uninitialized value as unspecified. Do not
    force ``str(value)`` in that state: RadioSettingValueString may legally
    return None internally after a driver rejected an invalid image value.
    """
    initialized = bool(_safe_attr(value, "initialized", True))
    if not initialized:
        return None
    cls = value.__class__.__name__
    try:
        if "Boolean" in cls:
            return bool(value.get_value())
        if "Integer" in cls:
            return _safe_int(value.get_value(), 0)
        if "Float" in cls:
            return _safe_float(value.get_value(), 0.0)
        if "List" in cls or "Map" in cls:
            return str(value)
        return str(value).rstrip()
    except Exception:
        raw = _safe_attr(value, "get_value", lambda: None)()
        return None if raw is None else str(raw).rstrip()


def _charset_text(value):
    """Return one CHIRP RadioSettingValue charset as a plain string."""
    charset = _safe_attr(value, "_charset", None)
    if charset is None:
        getter = getattr(value, "get_charset", None)
        if callable(getter):
            try:
                charset = getter()
            except Exception:
                charset = None
    if charset is None:
        return ""
    if isinstance(charset, str):
        return charset
    try:
        return "".join(str(ch) for ch in charset)
    except Exception:
        return str(charset)


def _feature_valid_characters_text(rf):
    """Return RadioFeatures.valid_characters without inventing a charset."""
    charset = _safe_attr(rf, "valid_characters", "")
    if charset is None:
        return ""
    if isinstance(charset, str):
        return charset
    try:
        return "".join(str(ch) for ch in charset)
    except Exception:
        return str(charset)


def _normalize_case_to_charset(value, charset):
    """Map an unsupported character to its uppercase form only when allowed.

    This is deliberately narrower than filtering/replacement: characters which
    are not accepted in either case are left untouched for CHIRP's normal
    validation path. Radios which already allow lowercase are unchanged.
    """
    text = str(value)
    allowed = set(str(charset or ""))
    if not allowed:
        return text
    out = []
    for ch in text:
        if ch in allowed:
            out.append(ch)
            continue
        upper = ch.upper()
        if len(upper) == 1 and upper in allowed:
            out.append(upper)
        else:
            out.append(ch)
    return "".join(out)



def _radio_text_for_compare(value):
    """Normalize only radio padding for an exact stored-text comparison."""
    if value is None:
        return ""
    return str(value).rstrip(" \x00\xff")


def _has_lowercase_text(value):
    text = "" if value is None else str(value)
    return any(ch.islower() for ch in text)


def _setting_to_dict(setting, group, setting_id=None, group_path=(),
                     component_index=0, component_count=None):
    """Serialize one CHIRP RadioSettingValue component to the neutral schema."""
    keys = [int(x) for x in setting.keys()]
    if not keys:
        raise ValueError("CHIRP RadioSetting contains no values")
    if component_index not in keys:
        raise ValueError("CHIRP RadioSetting component is unavailable")
    value = setting[component_index]
    total = int(component_count if component_count is not None else len(keys))
    cls = value.__class__.__name__
    base_label = str(getattr(setting, "get_shortname", lambda: setting.get_name())())
    label = base_label if total <= 1 else "%s %d" % (base_label, keys.index(component_index) + 1)
    initialized = bool(_safe_attr(value, "initialized", True))
    out = {
        "id": str(setting_id or ""),
        "name": setting.get_name(),
        "label": label,
        "group": group,
        "groupPath": list(group_path or ()),
        "componentIndex": int(component_index),
        "componentCount": total,
        "initialized": initialized,
        "value": _setting_value_for_ui(value),
        "mutable": bool(value.get_mutable()),
        "kind": "string",
    }
    try:
        out["doc"] = setting.__doc__ or ""
    except Exception:
        out["doc"] = ""
    if "Boolean" in cls:
        out["kind"] = "boolean"
    elif "List" in cls or "Map" in cls:
        out["kind"] = "list"
        try:
            out["options"] = [str(x) for x in (value.get_options() or [])]
        except Exception:
            out["options"] = []
    elif "Integer" in cls:
        out["kind"] = "integer"
        out["min"] = _safe_int(value.get_min(), 0)
        out["max"] = _safe_int(value.get_max(), 0)
        step = _safe_attr(value, "get_step", None)
        out["step"] = _safe_int(step(), 1) if callable(step) else 1
    elif "Float" in cls:
        out["kind"] = "number"
        out["min"] = _safe_float(value.get_min(), 0.0)
        out["max"] = _safe_float(value.get_max(), 0.0)
    else:
        try:
            out["minLength"] = int(value.minlength)
        except Exception:
            pass
        try:
            out["maxLength"] = int(value.maxlength)
        except Exception:
            pass
        charset = _charset_text(value)
        if charset:
            out["validCharacters"] = charset
    return out

def _settings_list(radio):
    """Flatten settings for display while retaining CHIRP's exact tree identity.

    Multi-value RadioSetting objects become multiple neutral rows, matching
    desktop CHIRP's one-property-per-RadioSettingValue behavior.
    """
    try:
        root = radio.get_settings()
    except Exception:
        return []
    if root is None:
        return []

    result = []
    for setting, index_path, group_names, group_label in _walk_settings_tree(root):
        keys = [int(x) for x in setting.keys()]
        for component_index in keys:
            try:
                sid = _setting_id(
                    index_path,
                    component_index if len(keys) > 1 else None,
                )
                result.append(_setting_to_dict(
                    setting,
                    group_label,
                    setting_id=sid,
                    group_path=group_names,
                    component_index=component_index,
                    component_count=len(keys),
                ))
            except Exception:
                # One firmware-specific/unsupported value must not hide the rest
                # of the driver's settings, matching CHIRP's tolerant UI intent.
                continue
    return result

def _mapping_id(mapping):
    try:
        return str(mapping.get_index())
    except Exception:
        return str(mapping)


def _bank_state_for_radio(radio, rf=None):
    if rf is None:
        rf = radio.get_features()
    if not _feature_bool(rf, "has_bank", False):
        return {"supported": False, "banks": []}

    try:
        model = radio.get_bank_model()
        mappings = list(model.get_mappings() or [])
    except Exception as exc:
        return {
            "supported": False,
            "banks": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    model_name = model.__class__.__name__
    editable = model_name != "StaticBankModel"
    multi = False
    indexed = False
    index_bounds = None
    try:
        from chirp import chirp_common
        multi = isinstance(model, chirp_common.MTOBankModel)
        indexed = isinstance(model, chirp_common.MappingModelIndexInterface)
    except Exception:
        multi = "MTO" in model_name
        indexed = all(callable(getattr(model, name, None)) for name in
                      ("get_memory_index", "set_memory_index", "get_index_bounds"))
    if indexed:
        try:
            index_bounds = [int(x) for x in model.get_index_bounds()]
        except Exception:
            index_bounds = None

    banks = []
    for mapping_index, mapping in enumerate(mappings):
        try:
            members = model.get_mapping_memories(mapping) or []
        except TypeError:
            # CHIRP StaticBankModel in this pinned revision uses Python-2 style
            # `/` when calculating the integer bank size, so Python 3 produces
            # a float and range(count) fails. Recreate that model's intended
            # fixed mapping here without modifying vendored CHIRP core.
            if model_name != "StaticBankModel" or not mappings:
                members = []
            else:
                try:
                    lo, hi = [int(x) for x in rf.memory_bounds]
                    num_banks = int(getattr(model, "_num_banks", 0) or len(mappings))
                    if num_banks <= 0:
                        raise ValueError("Static bank model has no banks")
                    count = (hi - lo + 1) // num_banks
                    try:
                        bank_index = int(mapping.get_index())
                    except Exception:
                        bank_index = mapping_index + 1
                    offset = lo + ((bank_index - 1) * count)
                    members = [radio.get_memory(offset + i)
                               for i in range(int(count))]
                except Exception:
                    members = []
        except Exception:
            members = []
        nums = []
        member_indexes = {}
        for mem in members:
            try:
                if not bool(_safe_attr(mem, "empty", False)):
                    number = int(mem.number)
                    nums.append(number)
                    if indexed:
                        try:
                            member_indexes[str(number)] = int(
                                model.get_memory_index(mem, mapping))
                        except Exception:
                            pass
            except Exception:
                continue
        banks.append({
            "id": _mapping_id(mapping),
            "name": str(_safe_attr(mapping, "get_name", lambda: str(mapping))()),
            "members": sorted(set(nums)),
            "memberIndexes": member_indexes,
        })

    return {
        "supported": True,
        "editable": editable,
        "multi": multi,
        "indexed": indexed,
        "indexBounds": index_bounds,
        "hasNames": _feature_bool(rf, "has_bank_names", False),
        "model": model_name,
        "banks": banks,
    }

def _find_bank_mapping(model, mapping_id):
    wanted = str(mapping_id)
    for mapping in model.get_mappings() or []:
        if _mapping_id(mapping) == wanted:
            return mapping
    raise ValueError(f"Unknown bank {mapping_id}")


def set_bank_json(mapping_id, bank_name, members_json):
    """Update one bank in the working image without touching radio hardware."""
    from chirp import chirp_common

    radio = _radio_from_image_bytes()
    rf = radio.get_features()
    if not _feature_bool(rf, "has_bank", False):
        raise ValueError("This radio does not support banks.")

    model = radio.get_bank_model()
    if model.__class__.__name__ == "StaticBankModel":
        raise ValueError("This radio has fixed banks and does not allow reassignment.")

    mapping = _find_bank_mapping(model, mapping_id)
    raw_members = _json.loads(members_json) or []
    desired = set()
    desired_indexes = {}
    for item in raw_members:
        if isinstance(item, dict):
            n = int(item.get("number"))
            desired.add(n)
            if item.get("index") is not None:
                desired_indexes[n] = int(item.get("index"))
        else:
            desired.add(int(item))
    low, high = [int(x) for x in rf.memory_bounds]
    desired = {n for n in desired if low <= n <= high}
    desired_indexes = {n: i for n, i in desired_indexes.items() if n in desired}

    if _feature_bool(rf, "has_bank_names", False) and bank_name is not None:
        name = str(bank_name)
        setter = _safe_attr(mapping, "set_name", None)
        if callable(setter):
            setter(name)

    mappings = list(model.get_mappings() or [])
    is_multi = isinstance(model, chirp_common.MTOBankModel)

    for n in range(low, high + 1):
        mem = radio.get_memory(n)
        if bool(_safe_attr(mem, "empty", False)):
            continue
        try:
            current = list(model.get_memory_mappings(mem) or [])
        except Exception:
            current = []
        current_ids = {_mapping_id(x) for x in current}
        target_id = _mapping_id(mapping)

        if n in desired:
            if not is_multi:
                for other in current:
                    if _mapping_id(other) != target_id:
                        model.remove_memory_from_mapping(mem, other)
            if target_id not in current_ids:
                model.add_memory_to_mapping(mem, mapping)
        elif target_id in current_ids:
            model.remove_memory_from_mapping(mem, mapping)

    if desired_indexes and isinstance(model, chirp_common.MappingModelIndexInterface):
        for n, index in desired_indexes.items():
            mem = radio.get_memory(n)
            if bool(_safe_attr(mem, "empty", False)):
                continue
            model.set_memory_index(mem, mapping, int(index))

    _save_working_radio(radio)
    return pocketchirp_radio_document_json()


def _dupe_memory(mem):
    try:
        return mem.dupe()
    except Exception:
        import copy
        return copy.deepcopy(mem)


def _capture_bank_memberships(radio, slots):
    rf = radio.get_features()
    if not _feature_bool(rf, "has_bank", False):
        return None
    try:
        from chirp import chirp_common
        model = radio.get_bank_model()
        if model.__class__.__name__ == "StaticBankModel":
            return None
        indexed = isinstance(model, chirp_common.MappingModelIndexInterface)
        result = {}
        for n in slots:
            mem = radio.get_memory(n)
            try:
                current = list(model.get_memory_mappings(mem) or [])
                if indexed:
                    rows = []
                    for mapping in current:
                        row = {"id": _mapping_id(mapping)}
                        try:
                            row["index"] = int(model.get_memory_index(mem, mapping))
                        except Exception:
                            pass
                        rows.append(row)
                    result[n] = rows
                else:
                    result[n] = [_mapping_id(x) for x in current]
            except Exception:
                result[n] = []
        return result
    except Exception:
        return None

def _restore_bank_memberships(radio, desired_by_slot):
    if not desired_by_slot:
        return
    try:
        from chirp import chirp_common
        model = radio.get_bank_model()
        mappings = list(model.get_mappings() or [])
        by_id = {_mapping_id(x): x for x in mappings}
        is_multi = isinstance(model, chirp_common.MTOBankModel)
        indexed = isinstance(model, chirp_common.MappingModelIndexInterface)

        for n, desired_rows in desired_by_slot.items():
            mem = radio.get_memory(n)
            try:
                current = list(model.get_memory_mappings(mem) or [])
            except Exception:
                current = []
            current_ids = {_mapping_id(x) for x in current}
            desired_ids = set()
            desired_indexes = {}
            for row in desired_rows:
                if isinstance(row, dict):
                    mid = str(row.get("id"))
                    desired_ids.add(mid)
                    if row.get("index") is not None:
                        desired_indexes[mid] = int(row.get("index"))
                else:
                    desired_ids.add(str(row))

            for mapping in current:
                mid = _mapping_id(mapping)
                if mid not in desired_ids:
                    model.remove_memory_from_mapping(mem, mapping)

            if not bool(_safe_attr(mem, "empty", False)):
                if not is_multi and desired_ids:
                    desired_ids = {next(iter(desired_ids))}
                for mid in desired_ids:
                    if mid not in current_ids and mid in by_id:
                        model.add_memory_to_mapping(mem, by_id[mid])
                if indexed:
                    for mid, index in desired_indexes.items():
                        mapping = by_id.get(mid)
                        if mapping is not None:
                            model.set_memory_index(mem, mapping, int(index))
    except Exception:
        # Memory movement must remain usable on radios whose bank model is
        # unusual. Fixed/static banks naturally remain attached to slots.
        return

# =============================================================================
# HARD REGRESSION GUARD — CHANNEL INSERT USES DIRECT SPREADSHEET ROW COPYING
# =============================================================================
# Insert Above/Below is intentionally simple. DO NOT route it through Move/Shift,
# DO NOT use an empty channel as a synthetic source, and DO NOT stop at a nearer
# empty slot. Copy actual slot records one position at a time, then erase the new
# slot. This mirrors CHIRP/spreadsheet row insertion.
#
# Insert Below N: copy high-1 -> high ... N+1 -> N+2; erase N+1.
# Insert Above N: copy low+1 -> low ... N-1 -> N-2; erase N-1.
# The boundary slot in the shift direction must already be empty so no programmed
# channel is discarded.
#
# DO NOT change Move/Swap behavior here.
# DO NOT renumber special memories or cross a sub-device boundary.
# DO NOT weaken any radio/transport safeguards elsewhere in this file.
# =============================================================================


def _write_insert_row(radio, dest, replacement):
    """Relocate one CHIRP memory the same way desktop CHIRP insert-row does."""
    replacement = _dupe_memory(replacement)
    replacement.number = int(dest)
    if bool(_safe_attr(replacement, "empty", False)):
        erase = getattr(radio, "erase_memory", None)
        if callable(erase):
            erase(int(dest))
        else:
            radio.set_memory(replacement)
        return
    problems = radio.validate_memory(replacement)
    errors = [str(x) for x in problems if x.__class__.__name__ == "ValidationError"]
    if errors:
        raise ValueError("Memory %d: %s" % (int(dest), "; ".join(errors)))
    radio.set_memory(replacement)


def _erase_insert_row(radio, dest):
    erase = getattr(radio, "erase_memory", None)
    if callable(erase):
        erase(int(dest))
        return
    mem = _dupe_memory(radio.get_memory(int(dest)))
    mem.number = int(dest)
    mem.empty = True
    radio.set_memory(mem)


# =============================================================================
# HARD REGRESSION GUARD — INSERT ROW FOLLOWS DESKTOP CHIRP SEMANTICS
# =============================================================================
# Desktop CHIRP finds the FIRST empty ordinary memory at or below the insertion
# row, then walks backward from that hole, duplicating each source into the next
# slot, and finally erases the insertion row. This is the universal algorithm.
#
# Insert Above on N: insertion row is N. Old N moves to N+1.
# Insert Below on N: insertion row is N+1. Old N stays N.
#
# DO NOT require the last physical memory slot to be empty.
# DO NOT shift beyond the first empty memory.
# DO NOT clear copied Memory.immutable metadata merely because the row moves;
# desktop CHIRP's insert path duplicates the Memory and changes its number only.
# DO NOT renumber special memories or cross a sub-device boundary.
# =============================================================================
def _insert_memory_row_simple(radio, anchor, mode, low, high):
    anchor = int(anchor)
    low = int(low)
    high = int(high)
    mode = str(mode or "").lower()
    if anchor < low or anchor > high:
        raise ValueError("Memory must be between %d and %d." % (low, high))

    if mode == "insert_above":
        insert_at = anchor
    elif mode == "insert_below":
        insert_at = anchor + 1
        if insert_at > high:
            raise ValueError("Cannot insert below the last memory channel.")
    else:
        raise ValueError("Unknown memory insert mode.")

    # Match desktop CHIRP: traverse downward from the insertion row until the
    # first empty ordinary memory. That hole provides exactly one free row.
    empty_source = None
    for number in range(insert_at, high + 1):
        mem = radio.get_memory(number)
        if bool(_safe_attr(mem, "empty", False)):
            empty_source = int(number)
            break
    if empty_source is None:
        raise ValueError(
            "No empty channel at or below Memory %d. Insert cancelled so no "
            "programmed channel is discarded." % insert_at)

    # Snapshot the contiguous block before changing anything. Moving in reverse
    # order is essential: it preserves every source until its copy is committed.
    sources = list(range(insert_at, empty_source))
    originals = {n: _dupe_memory(radio.get_memory(n)) for n in sources}
    affected = list(range(insert_at, empty_source + 1))
    bank_before = _capture_bank_memberships(radio, affected)

    for src in reversed(sources):
        _write_insert_row(radio, src + 1, originals[src])

    _erase_insert_row(radio, insert_at)

    if bank_before is not None:
        desired = {insert_at: []}
        for src in sources:
            desired[src + 1] = list(bank_before.get(src, []))
        _restore_bank_memberships(radio, desired)

    return insert_at, {src + 1: originals[src] for src in sources}


def rearrange_memories_json(source_number, target_number, mode):
    """Swap, move/shift, or losslessly insert CHIRP memory records."""
    root_radio = _radio_from_image_bytes()
    views = _editor_radio_views(root_radio) if "_editor_radio_views" in globals() else [(root_radio, *root_radio.get_features().memory_bounds, *root_radio.get_features().memory_bounds, "")]
    if len(views) > 1:
        source = int(source_number); target = int(target_number); mode = str(mode or "").lower()
        src_radio, src_native, src_variant = _editor_memory_target(root_radio, source)

        # HARD SUB-DEVICE INSERT GUARD — INSERT IS ANCHORED TO ONE CHILD ONLY.
        #
        # Multi-band radios such as the Icom IC-W32A expose VHF and UHF as separate
        # CHIRP sub-devices which PocketCHIRP flattens only for display. Insert Above/
        # Below is not a source->destination move, so DO NOT resolve the UI target or
        # apply the cross-sub-device Move/Swap guard here. The held row selects the
        # child, and the nearest-empty search must remain inside that child's native
        # memory_bounds. This preserves the hard VHF/UHF boundary while still allowing
        # normal Move/Swap to reject an actual cross-boundary destination below.
        if mode in ("insert_above", "insert_below"):
            radio = src_radio
            rf = radio.get_features()
            child_low, child_high = [int(x) for x in rf.memory_bounds]
            _insert_memory_row_simple(radio, src_native, mode, child_low, child_high)
            _save_working_radio(root_radio)
            return pocketchirp_radio_document_json()

        # Move/Swap/Shift really do have a destination, so retain the existing hard
        # cross-sub-device rejection for those operations.
        dst_radio, dst_native, dst_variant = _editor_memory_target(root_radio, target)
        if src_radio is not dst_radio:
            raise ValueError("Move/swap between radio sub-devices is not supported. Keep VHF and UHF channels within their own side.")
        radio = src_radio; rf = radio.get_features()
        source_n=src_native; target_n=dst_native
        if source == target:
            return pocketchirp_radio_document_json()
        if mode not in ("swap", "shift", "move"): raise ValueError("Memory move mode must be swap, move, shift, insert_above, or insert_below.")
        # Translate PocketCHIRP display slots to this child's native slots, then use
        # the same safe move/swap behavior as ordinary radios.
        if mode == "move":
            target_mem=radio.get_memory(target_n)
            if not bool(_safe_attr(target_mem, "empty", False)): raise ValueError("Move is only available when the destination memory is empty.")
            slots=[source_n,target_n]; source_for_dest={source_n:target_n,target_n:source_n}
        elif mode == "swap":
            slots=[source_n,target_n]; source_for_dest={source_n:target_n,target_n:source_n}
        else:
            lo,hi=min(source_n,target_n),max(source_n,target_n); slots=list(range(lo,hi+1)); source_for_dest={}
            if source_n < target_n:
                for n in range(source_n,target_n): source_for_dest[n]=n+1
                source_for_dest[target_n]=source_n
            else:
                source_for_dest[target_n]=source_n
                for n in range(target_n+1,source_n+1): source_for_dest[n]=n-1
        originals={n:_dupe_memory(radio.get_memory(n)) for n in slots}; planned={}
        for dest,src in source_for_dest.items():
            mem=_dupe_memory(originals[src]); mem.number=dest; planned[dest]=mem
        for dest,replacement in planned.items():
            if not bool(_safe_attr(replacement, "empty", False)):
                problems = radio.validate_memory(replacement)
                errors = [
                    str(x) for x in problems
                    if x.__class__.__name__ == "ValidationError"
                ]
                if errors: raise ValueError(f"{src_variant} memory {dest}: "+"; ".join(errors))
        for dest in sorted(d for d,m in planned.items() if not bool(_safe_attr(m,"empty",False))): radio.set_memory(planned[dest])
        for dest in sorted(d for d,m in planned.items() if bool(_safe_attr(m,"empty",False))):
            erase=getattr(radio,"erase_memory",None)
            if callable(erase): erase(dest)
            else: radio.set_memory(planned[dest])
        _save_working_radio(root_radio)
        return pocketchirp_radio_document_json()

    radio = _radio_from_image_bytes()
    rf = radio.get_features()
    low, high = [int(x) for x in rf.memory_bounds]
    source = int(source_number)
    target = int(target_number)
    mode = str(mode or "").lower()

    if source < low or source > high or target < low or target > high:
        raise ValueError(f"Memory must be between {low} and {high}.")
    if mode in ("insert_above", "insert_below"):
        blank_target, expected = _insert_memory_row_simple(radio, source, mode, low, high)
        # Save first, then rebuild the returned editor state from the saved image.
        # Do not gate UI refresh on a strict Memory fingerprint comparison: drivers
        # are allowed to normalize representation details when an image is reloaded.
        _save_working_radio(radio)
        return pocketchirp_radio_document_json()
    elif source == target:
        return pocketchirp_radio_document_json()
    if mode not in ("swap", "shift", "move"):
        raise ValueError("Memory move mode must be swap, move, shift, insert_above, or insert_below.")

    if source == target:
        # The requested adjacent slot was already empty.
        return pocketchirp_radio_document_json()

    if mode == "move":
        target_mem = radio.get_memory(target)
        if not bool(_safe_attr(target_mem, "empty", False)):
            raise ValueError("Move is only available when the destination memory is empty.")
        slots = [source, target]
        source_for_dest = {source: target, target: source}
    elif mode == "swap":
        slots = [source, target]
        source_for_dest = {source: target, target: source}
    else:
        lo, hi = min(source, target), max(source, target)
        slots = list(range(lo, hi + 1))
        source_for_dest = {}
        if source < target:
            for n in range(source, target):
                source_for_dest[n] = n + 1
            source_for_dest[target] = source
        else:
            source_for_dest[target] = source
            for n in range(target + 1, source + 1):
                source_for_dest[n] = n - 1

    originals = {n: _dupe_memory(radio.get_memory(n)) for n in slots}
    bank_before = _capture_bank_memberships(radio, slots)
    desired_banks = None
    if bank_before is not None:
        desired_banks = {
            dest: list(bank_before.get(src, []))
            for dest, src in source_for_dest.items()
        }

    planned = {}
    for dest, src in source_for_dest.items():
        mem = _dupe_memory(originals[src])
        mem.number = dest
        planned[dest] = mem

    for dest in sorted(planned):
        current = radio.get_memory(dest)
        replacement = planned[dest]
        is_empty = bool(_safe_attr(replacement, "empty", False))
        if is_empty and not _feature_bool(rf, "can_delete", True):
            raise ValueError("This radio does not allow deleting/emptying memories.")

        # Empty CHIRP memories are valid move/swap destinations, but many
        # drivers expect erase_memory() rather than set_memory(empty_memory).
        # Only validate populated replacements; an empty slot may intentionally
        # omit fields which a driver's validator expects on programmed memories.
        if not is_empty:
            problems = radio.validate_memory(replacement)
            errors = [str(x) for x in problems
                      if x.__class__.__name__ == "ValidationError"]
            if errors:
                raise ValueError(f"Memory {dest}: " + "; ".join(errors))

        # CHIRP's immutable-policy helper is designed around setting a
        # populated Memory object. An intentionally empty replacement may omit
        # fields which are meaningless for an erased slot, and some drivers
        # reject that object even though erase_memory(dest) is valid. Keep the
        # policy check for actual programmed replacements and use the driver's
        # erase path for empty destinations below.
        if not is_empty and not bool(_safe_attr(current, "empty", False)):
            # Moving a populated channel into an empty slot must not be blocked
            # by immutable metadata attached to the empty placeholder object.
            radio.check_set_memory_immutable_policy(current, replacement)

    # Write all populated destinations first. This preserves every source
    # record until its replacement has been committed, which is particularly
    # important when swapping/moving a programmed memory into an empty slot.
    populated = [d for d, m in planned.items()
                 if not bool(_safe_attr(m, "empty", False))]
    emptied = [d for d, m in planned.items()
               if bool(_safe_attr(m, "empty", False))]

    for dest in sorted(populated):
        radio.set_memory(planned[dest])

    for dest in sorted(emptied):
        replacement = planned[dest]
        erase = getattr(radio, "erase_memory", None)
        if callable(erase):
            erase(dest)
        else:
            radio.set_memory(replacement)

    _restore_bank_memberships(radio, desired_banks)
    _save_working_radio(radio)
    return pocketchirp_radio_document_json()




# Stock configurations copied from the bundled CHIRP source tree.
# This fallback keeps PocketCHIRP presets available even when the Android
# Python packaging step does not preserve chirp/stock_configs as resources.
_POCKETCHIRP_STOCK_CONFIGS = {
    'AU NZ UHF Citizens Band.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,CB 01RP,476.425,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 01 duplex,,,\n2,CB 02RP,476.45,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 02 duplex,,,\n3,CB 03RP,476.475,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 03 duplex,,,\n4,CB 04RP,476.5,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 04 duplex,,,\n5,CB 05,476.525,,,,88.5,88.5,23,NN,NFM,12.5,,Channel 05 emergency simplex,,,\n6,CB 05RP,476.525,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 05 emergency duplex,,,\n7,CB 06RP,476.55,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 06 duplex,,,\n8,CB 07RP,476.575,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 07 duplex,,,\n9,CB 08RP,476.6,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 08 duplex,,,\n10,CB 09,476.625,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n11,CB 10,476.65,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n12,CB 11,476.675,,,,88.5,88.5,23,NN,NFM,12.5,,AU CB Call channel,,,\n13,CB 12,476.7,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n14,CB 13,476.725,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n15,CB 14,476.75,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n16,CB 15,476.775,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n17,CB 16,476.8,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n18,CB 17,476.825,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n19,CB 18,476.85,,,,88.5,88.5,23,NN,NFM,12.5,,"Caravan, RV & Convoy channel",,,\n20,CB 19,476.875,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n21,CB 20,476.9,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n22,CB 21,476.925,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n23,CB 22T,476.95,,,,88.5,88.5,23,NN,NFM,12.5,,Telemetery & Telecommand (no voice allowed),,,\n24,CB 23T,476.975,,,,88.5,88.5,23,NN,NFM,12.5,,Telemetery & Telecommand (no voice allowed),,,\n25,CB 24,477,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n26,CB 25,477.025,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n27,CB 26,477.05,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n28,CB 27,477.075,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n29,CB 28,477.1,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n30,CB 29,477.125,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n31,CB 30,477.15,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n32,CB 31,477.175,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 1 repeater input (use chan 1 duplex for repeater),,,\n33,CB 32,477.2,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 2 repeater input (use chan 2 duplex for repeater),,,\n34,CB 33,477.225,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 3 repeater input (use chan 3 duplex for repeater),,,\n35,CB 34,477.25,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 4 repeater input (use chan 4 duplex for repeater),,,\n36,CB 35,477.275,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 5 EMERGENCY repeater input (use chan 5 duplex for repeater),,,\n37,CB 36,477.3,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 6 repeater input (use chan 6 duplex for repeater),,,\n38,CB 37,477.325,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 7 repeater input (use chan 7 duplex for repeater),,,\n39,CB 38,477.35,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 8 repeater input (use chan 8 duplex for repeater),,,\n40,CB 39,477.375,,,,88.5,88.5,23,NN,NFM,12.5,,Road safety channel secondary,,,\n41,CB 40,477.4,,,,88.5,88.5,23,NN,NFM,12.5,,Road safety channel primary,,,\n42,CB 41R,476.4375,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 41 duplex,,,\n43,CB 42R,476.4625,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 42 duplex,,,\n44,CB 43R,476.4875,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 43 duplex,,,\n45,CB 44R,476.5125,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 44 duplex,,,\n46,CB 45R,476.5375,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 45 duplex,,,\n47,CB 46R,476.5625,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 46 duplex,,,\n48,CB 47R,476.5875,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 47 duplex,,,\n49,CB 48R,476.6125,+,0.75,,88.5,88.5,23,NN,NFM,12.5,,Channel 48 duplex,,,\n50,CB 49,476.6375,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n51,CB 50,476.6625,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n52,CB 51,476.6875,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n53,CB 52,476.7125,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n54,CB 53,476.7375,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n55,CB 54,476.7625,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n56,CB 55,476.7875,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n57,CB 56,476.8125,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n58,CB 57,476.8375,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n59,CB 58,476.8625,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n60,CB 59,476.8875,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n61,CB 60,476.9125,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n62,CB 61*,476.9375,,,,88.5,88.5,23,NN,NFM,12.5,,Reserved for future use,,,\n63,CB 62*,476.9625,,,,88.5,88.5,23,NN,NFM,12.5,,Reserved for future use,,,\n64,CB 63*,476.9875,,,,88.5,88.5,23,NN,NFM,12.5,,Reserved for future use,,,\n65,CB 64,477.0125,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n66,CB 65,477.0375,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n67,CB 66,477.0625,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n68,CB 67,477.0875,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n69,CB 68,477.1125,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n70,CB 69,477.1375,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n71,CB 70,477.1625,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n72,CB 71R,477.1875,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 41 repeater input (use chan 41 duplex for repeater),,,\n73,CB 72R,477.2125,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 42 repeater input (use chan 42 duplex for repeater),,,\n74,CB 73R,477.2375,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 43 repeater input (use chan 43 duplex for repeater),,,\n75,CB 74R,477.2625,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 44 repeater input (use chan 44 duplex for repeater),,,\n76,CB 75R,477.2875,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 45 repeater input (use chan 45 duplex for repeater),,,\n77,CB 76R,477.3125,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 46 repeater input (use chan 46 duplex for repeater),,,\n78,CB 77R,477.3375,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 47 repeater input (use chan 47 duplex for repeater),,,\n79,CB 78R,477.3625,,,,88.5,88.5,23,NN,NFM,12.5,,Chan 48 repeater input (use chan 48 duplex for repeater),,,\n80,CB 79,477.3875,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n81,CB 80,477.4125,,,,88.5,88.5,23,NN,NFM,12.5,,,,,\n',
    'CA Calling Frequencies.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,6m Call,52.525000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n2,2m Call,146.520000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n3,70cm Call,446.000000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n4,33cm Call,904.500000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n5,23cm Call,1294.500000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n6,13cm Call,2305.200000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n',
    'CA FRS and GMRS Channels.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,FRS 1,462.562500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n2,FRS 2,462.587500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n3,FRS 3,462.612500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n4,FRS 4,462.637500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n5,FRS 5,462.662500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n6,FRS 6,462.687500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n7,FRS 7,462.712500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n8,FRS 8,467.562500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n9,FRS 9,467.587500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n10,FRS 10,467.612500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n11,FRS 11,467.637500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n12,FRS 12,467.662500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n13,FRS 13,467.687500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n14,FRS 14,467.712500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n15,GMRS 1,462.550000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n16,GMRS 2,462.562500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n17,GMRS 3,462.575000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n18,GMRS 4,462.587500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n19,GMRS 5,462.600000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n20,GMRS 6,462.612500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n21,GMRS 7,462.625000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n22,GMRS 8,462.637500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n23,GMRS 9,462.650000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n24,GMRS 10,462.662500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n25,GMRS 11,462.675000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n26,GMRS 12,462.687500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n27,GMRS 13,462.700000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n28,GMRS 14,462.712500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n29,GMRS 15,462.725000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,,,,\n',
    'DE Freenet Frequencies.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,FRNET1,149.025000,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n2,FRNET2,149.037500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n3,FRNET3,149.050000,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n4,FRNET4,149.087500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n5,FRNET5,149.100000,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n6,FRNET6,149.112500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n',
    'EU LPD and PMR Channels.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,LPD 01,433.075000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n2,LPD 02,433.100000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n3,LPD 03,433.125000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n4,LPD 04,433.150000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n5,LPD 05,433.175000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n6,LPD 06,433.200000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n7,LPD 07,433.225000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n8,LPD 08,433.250000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n9,LPD 09,433.275000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n10,LPD 10,433.300000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n11,LPD 11,433.325000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n12,LPD 12,433.350000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n13,LPD 13,433.375000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n14,LPD 14,433.400000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n15,LPD 15,433.425000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n16,LPD 16,433.450000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n17,LPD 17,433.475000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n18,LPD 18,433.500000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n19,LPD 19,433.525000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n20,LPD 20,433.550000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n21,LPD 21,433.575000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n22,LPD 22,433.600000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n23,LPD 23,433.625000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n24,LPD 24,433.650000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n25,LPD 25,433.675000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n26,LPD 26,433.700000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n27,LPD 27,433.725000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n28,LPD 28,433.750000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n29,LPD 29,433.775000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n30,LPD 30,433.800000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n31,LPD 31,433.825000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n32,LPD 32,433.850000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n33,LPD 33,433.875000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n34,LPD 34,433.900000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n35,LPD 35,433.925000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n36,LPD 36,433.950000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n37,LPD 37,433.975000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n38,LPD 38,434.000000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n39,LPD 39,434.025000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n40,LPD 40,434.050000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n41,LPD 41,434.075000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n42,LPD 42,434.100000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n43,LPD 43,434.125000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n44,LPD 44,434.150000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n45,LPD 45,434.175000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n46,LPD 46,434.200000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n47,LPD 47,434.225000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n48,LPD 48,434.250000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n49,LPD 49,434.275000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n50,LPD 50,434.300000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n51,LPD 51,434.325000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n52,LPD 52,434.350000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n53,LPD 53,434.375000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n54,LPD 54,434.400000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n55,LPD 55,434.425000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n56,LPD 56,434.450000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n57,LPD 57,434.475000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n58,LPD 58,434.500000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n59,LPD 59,434.525000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n60,LPD 60,434.550000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n61,LPD 61,434.575000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n62,LPD 62,434.600000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n63,LPD 63,434.625000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n64,LPD 64,434.650000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n65,LPD 65,434.675000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n66,LPD 66,434.700000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n67,LPD 67,434.725000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n68,LPD 68,434.750000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n69,LPD 69,434.775000,,0.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n71,PMR 01,446.006250,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n72,PMR 02,446.018750,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n73,PMR 03,446.031250,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n74,PMR 04,446.043750,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n75,PMR 05,446.056250,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n76,PMR 06,446.068750,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n77,PMR 07,446.081250,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n78,PMR 08,446.093750,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n81,PMR 09,446.106250,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n82,PMR 10,446.118750,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n83,PMR 11,446.131250,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n84,PMR 12,446.143750,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n85,PMR 13,446.156250,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n86,PMR 14,446.168750,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n87,PMR 15,446.181250,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n88,PMR 16,446.193750,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n',
    'FR Marine VHF Channels.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,SEA 01,160.650000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n2,SEA 02,160.700000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n3,SEA 03,160.750000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n4,SEA 04,160.800000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n5,SEA 05,160.850000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n6,SEA 06,156.300000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n7,SEA 07,160.950000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n8,SEA 08,156.400000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n9,SEA 09,156.450000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n10,SEA 10,156.500000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n11,SEA 11,156.550000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n12,SEA 12,156.600000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n13,SEA 13,156.650000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n14,SEA 14,156.700000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n15,SEA 15,156.750000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n16,SEA 16,156.800000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n17,SEA 17,156.850000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n18,SEA 18,161.500000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n19,SEA 19,161.550000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n20,SEA 20,161.600000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n21,SEA 21,161.650000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n22,SEA 22,161.700000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n23,SEA 23,161.750000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n24,SEA 24,161.800000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n25,SEA 25,161.850000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n26,SEA 26,161.900000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n27,SEA 27,161.950000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n28,SEA 28,162.000000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n29,SEA 60,160.625000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n30,SEA 61,160.675000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n31,SEA 62,160.725000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n32,SEA 63,160.775000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n33,SEA 64,160.825000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n34,SEA 65,160.875000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n35,SEA 66,160.925000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n36,SEA 67,156.375000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n37,SEA 68,156.425000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n38,SEA 69,156.475000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n39,SEA 70,156.525000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n40,SEA 71,156.575000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n41,SEA 72,156.625000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n42,SEA 73,156.675000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n43,SEA 74,156.725000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n44,SEA 75,156.775000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n45,SEA 76,156.825000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n46,SEA 77,156.875000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n47,SEA 78,161.525000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n48,SEA 79,161.575000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n49,SEA 80,161.625000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n50,SEA 81,161.675000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n51,SEA 82,161.725000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n52,SEA 83,161.775000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n53,SEA 84,161.825000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n54,SEA 85,161.875000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n55,SEA 86,161.925000,-,4.600000,,88.5,88.5,023,NN,FM,5.00,,,,,\n56,SEA 87,157.375000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n57,SEA 88,157.425000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n',
    'GR Marine VHF Channels.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,RxDtcsCode,CrossMode,Mode,TStep,Skip,Power,Comment,URCALL,RPT1CALL,RPT2CALL,DVCODE\n1,MRN 01,160.650000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n2,MRN 02,160.700000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n3,MRN 03,160.750000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n4,MRN 04,160.800000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n5,MRN 05,160.850000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n6,MRN 06,156.300000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n7,MRN 07,160.950000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n8,MRN 08,156.400000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n9,MRN 09,156.450000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n10,MRN 10,156.500000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n11,MRN 11,156.550000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n12,MRN 12,156.600000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n13,MRN 13,156.650000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n14,MRN 14,156.700000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n15,MRN 15,156.750000,off,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n16,MRN 16,156.800000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n17,MRN 17,156.850000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n18,MRN 18,161.500000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n19,MRN 19,161.550000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n20,MRN 20,161.600000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n21,MRN 21,161.650000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n22,MRN 22,161.700000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n23,MRN 23,161.750000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n24,MRN 24,161.800000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n25,MRN 25,161.850000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n26,MRN 26,161.900000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n27,MRN 27,161.950000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n28,MRN 28,162.000000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n29,MRN 60,160.625000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n30,MRN 61,160.675000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n31,MRN 62,160.725000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n32,MRN 63,160.775000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n33,MRN 64,160.825000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n34,MRN 65,160.875000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n35,MRN 66,160.925000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n36,MRN 67,156.375000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n37,MRN 68,156.425000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n38,MRN 69,156.475000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n39,MRN 70,156.525000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n40,MRN 71,156.575000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n41,MRN 72,156.625000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n42,MRN 73,156.675000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n43,MRN 74,156.725000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n44,MRN 75,156.775000,off,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n45,MRN 76,156.825000,off,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n46,MRN 77,156.875000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n47,MRN 78,161.525000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n48,MRN 79,161.575000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n49,MRN 80,161.625000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n50,MRN 81,161.675000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n51,MRN 82,161.725000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n52,MRN 83,161.775000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n53,MRN 84,161.825000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n54,MRN 85,161.875000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n55,MRN 86,161.925000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,50W,,,,,\n56,MRN 87,161.975000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,,,,,\n57,MRN 88,162.025000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,,,,,\n',
    'PL Calling Frequencies and Simplex.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,RxDtcsCode,CrossMode,Mode,TStep,Skip,Power,Comment,URCALL,RPT1CALL,RPT2CALL,DVCODE\n0,VHF SSTV,144.500000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Częstotliwość SSTV,,,,\n1,VHF APRS,144.800000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Częstotliwość APRS 2m,,,,\n2,VHF WX,144.950000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Częstotliwość pracy stacji pogodowych SR0WX ,,,,\n3,VHF CQ,145.375000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Częstotliwość wywoławcza,,,,\n4,VHF CQ M,145.500000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Częstotliwość wywoławcza dla stacji mobilnych oraz EMCOM,,,,\n5,VHF SOTA,145.550000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,"[2m] Częstotliwość wywoławcza programów SOTA,POTA oraz podobnych",,,,\n7,UHF APRS,432.500000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Częstotliwość APRS 70cm,,,,\n8,UHF CQ,433.450000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Częstotliwość wywoławcza,,,,\n9,UHF CQ M,433.500000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Częstotliwość wywoławcza dla stacji mobilnych oraz EMCOM,,,,\n11,,145.212500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n12,,145.225000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n13,,145.250000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n14,,145.262500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n15,,145.275000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n16,,145.300000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n17,,145.312500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n18,,145.325000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n19,,145.350000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n20,,145.362500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n21,VHF CQ,145.375000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Częstotliwość wywoławcza,,,,\n22,,145.387500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n23,,145.400000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n24,,145.412500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n25,,145.425000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n26,,145.437500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n27,,145.450000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n28,,145.462500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n29,,145.475000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n30,,145.487500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n31,VHF CQ M,145.500000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Częstotliwość wywoławcza dla stacji mobilnych oraz EMCOM,,,,\n32,,145.512500,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n33,,145.525000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n34,,145.537500,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n35,VHF SOTA,145.550000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,"[2m] Częstotliwość wywoławcza programów SOTA,POTA oraz podobnych",,,,\n36,,145.562500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[2m] Kanał FM/DV,,,,\n38,,433.400000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n39,,433.412500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n40,,433.425000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n41,,433.437500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n42,UHF CQ,433.450000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Częstotliwość wywoławcza,,,,\n43,,433.462500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n44,,433.475000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n45,,433.487500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n46,UHF CQ M,433.500000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Częstotliwość wywoławcza dla stacji mobilnych oraz EMCOM,,,,\n47,,433.512500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n48,,433.525000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n49,,433.537500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n50,,433.550000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n51,,433.562500,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n52,,433.575000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,12.50,,5.0W,[70cm] Kanał FM/DV,,,,\n',
    'SE Jaktradio 155MHz.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,JAKT 1,155.425,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n2,JAKT 2,155.475,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n3,JAKT 3,155.500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n4,JAKT 4,155.525,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n5,JAKT 5,156.000,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n6,JAKT 6,155.400,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n7,JAKT 7,155.450,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n',
    'SE NO KDR444.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,KDR444 1,444.600,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n2,KDR444 2,444.650,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n3,KDR444 3,444.800,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n4,KDR444 4,444.825,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n5,KDR444 5,444.850,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n6,KDR444 6,444.875,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n7,KDR444 7,444.925,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n8,KDR444 8,444.975,,0.600000,,88.5,88.5,023,NN,NFM,6.25,,,,,\n',
    'UK Business Radio Simple Light Frequencies.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,BRSL1,77.687500,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n2,BRSL2,86.337500,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n3,BRSL3,86.350000,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n4,BRSL4,86.362500,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n5,BRSL5,86.375000,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n6,BRSL6,164.050000,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n7,BRSL7,164.062500,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n8,BRSL8,169.087500,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n9,BRSL9,169.312500,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n10,BRSL10,173.050000,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n11,BRSL11,173.062500,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n12,BRSL12,173.087500,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n13,BRSL13,449.312500,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n14,BRSL14,449.400000,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n15,BRSL15,449.475000,,0.000000,,88.5,88.5,023,NN,NFM,12.50,,,,,\n',
    'US 60 meter channels (Center).csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,60m CH1,5.332000,,0.600000,,88.5,88.5,023,NN,USB,5.00,,,,,\n2,60m CH2,5.348000,,0.600000,,88.5,88.5,023,NN,USB,5.00,,,,,\n3,60m CH3,5.358500,,0.600000,,88.5,88.5,023,NN,USB,5.00,,,,,\n4,60m CH4,5.373000,,0.600000,,88.5,88.5,023,NN,USB,5.00,,,,,\n5,60m CH5,5.405000,,0.600000,,88.5,88.5,023,NN,USB,5.00,,,,,\n',
    'US 60 meter channels (Dial).csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,60m CH1,5.330500,,0.600000,,88.5,88.5,023,NN,USB,5.00,,,,,\n2,60m CH2,5.346500,,0.600000,,88.5,88.5,023,NN,USB,5.00,,,,,\n3,60m CH3,5.357000,,0.600000,,88.5,88.5,023,NN,USB,5.00,,,,,\n4,60m CH4,5.371500,,0.600000,,88.5,88.5,023,NN,USB,5.00,,,,,\n5,60m CH5,5.403500,,0.600000,,88.5,88.5,023,NN,USB,5.00,,,,,\n',
    'US Aviation Frequencies.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,RxDtcsCode,CrossMode,Mode,TStep,Skip,Power,Comment,URCALL,RPT1CALL,RPT2CALL,DVCODE\n0,VHF Guard,121.500000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Aircraft Emergency and Distress,,,,\n1,ELT Training,121.775000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Emergency Locator Transmitter (ELT) Training Beacons,,,,\n2,AvSup 121.95,121.950000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Aviation Support,,,,\n3,FLightWatch WX,122.200000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Watch Weather ,,,,\n4,UNICOM 122.7,122.700000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,Airports without an Air Traffic Control tower or FSS on the airport.,,,,\n5,UNICOM 122.725,122.725000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,Airports without an Air Traffic Control tower or FSS on the airport.,,,,\n6,Air-Air Fixed Wing,122.750000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,USA: Air-to-air communication (private fixed wing aircraft).,,,,\n7,UNICOM 122.8,122.800000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,Airports without an Air Traffic Control tower or FSS on the airport.,,,,\n8,MULTICOM 122.85,122.850000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,"Multicom, Aviation Support",,,,\n9,MULTICOM 122.9,122.900000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,"Multicom, Search and Rescue Training \t",,,,\n10,MULTICOM 122.925,122.925000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,"Multicom, Special Use, Natural resource management \t",,,,\n11,UNICOM 122.95 (ATC),122.950000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,Airports with an Air Traffic Control tower or FSS (Alaska only) on the airport.,,,,\n12,UNICOM 122.975,122.975000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,Airports without an Air Traffic Control tower or FSS on the airport.,,,,\n13,UNICOM 123.0,123.000000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,Airports without an Air Traffic Control tower or FSS on the airport.,,,,\n14,Air-Air Helo,123.025000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,USA: Helicopter air-to-air communications; air traffic control operations.,,,,\n15,UNICOM 123.05,123.050000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,Airports without an Air Traffic Control tower or FSS on the airport.,,,,\n16,UNICOM 123.075,123.075000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,Airports without an Air Traffic Control tower or FSS on the airport.,,,,\n17,SAR Primary,123.100000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,"Search and Rescue primary, ATC for special events secondary.",,,,\n18,FlightTest 123.125,123.125000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test itinerant,,,,\n19,FlightTest 123.15,123.150000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test itinerant \t,,,,\n20,FlightTest 123.175,123.175000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test itinerant \t,,,,\n21,FlightTest 123.2,123.200000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test,,,,\n22,FlightTest 123.225,123.225000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test,,,,\n23,FlightTest 123.25,123.250000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test,,,,\n24,FlightTest 123.275,123.275000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test,,,,\n25,AvSup 123.3,123.300000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,"Aviation instruction, Glider, Hot Air Balloon (not to be used for advisory service).",,,,\n26,FlightTest 123.325,123.325000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test,,,,\n27,FlightTest 123.35,123.350000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,Flight Test,,,,\n28,FlightTest 123.375,123.375000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test,,,,\n29,FlightTest 123.4,123.400000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,Flight Test itinerant,,,,\n30,FlightTest 123.425,123.425000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test itinerant,,,,\n31,FlightTest 123.45,123.450000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,Flight Test,,,,\n32,FlightTest 123.475,123.475000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test,,,,\n33,AvSup 123.5,123.500000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,AM,25.00,,50W,"Aviation instruction, Glider, Hot Air Balloon (not to be used for advisory service).",,,,\n34,FlightTest 123.525,123.525000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test,,,,\n35,FlightTest 123.55,123.550000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test,,,,\n36,FlightTest 123.575,123.575000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Flight Test,,,,\n37,MILCOM 126.2,126.200000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Military Common (advisory) ,,,,\n38,Deicing Common,129.525000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Deicing Common,,,,\n39,MILCOM 134.1,134.100000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,Military Common (advisory) ,,,,\n40,FlightInsp 135.85,135.850000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,FAA Flight Inspection,,,,\n41,FlightInsp 135.9,135.900000,,0.600000,,88.5,88.5,023,NN,023,Tone->Tone,AM,5.00,,50W,FAA Flight Inspection,,,,\n',
    'US CA Railroad Channels.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,AAR002,159.810000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n2,AAR003,159.930000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n3,AAR004,160.050000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n4,AAR005,160.185000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n5,AAR006,160.200000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n6,AAR007,160.215000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n7,AAR008,160.230000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n8,AAR009,160.245000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n9,AAR010,160.260000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n10,AAR011,160.275000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n11,AAR012,160.290000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n12,AAR013,160.305000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n13,AAR014,160.320000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n14,AAR015,160.335000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n15,AAR016,160.350000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n16,AAR017,160.365000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n17,AAR018,160.380000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n18,AAR019,160.395000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n19,AAR020,160.410000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n20,AAR021,160.425000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n21,AAR022,160.440000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n22,AAR023,160.455000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n23,AAR024,160.470000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n24,AAR025,160.485000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n25,AAR026,160.500000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n26,AAR027,160.515000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n27,AAR028,160.530000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n28,AAR029,160.545000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n29,AAR030,160.560000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n30,AAR031,160.575000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n31,AAR032,160.590000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n32,AAR033,160.605000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n33,AAR034,160.620000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n34,AAR035,160.635000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n35,AAR036,160.650000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n36,AAR037,160.665000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n37,AAR038,160.680000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n38,AAR039,160.695000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n39,AAR040,160.710000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n40,AAR041,160.725000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n41,AAR042,160.740000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n42,AAR043,160.755000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n43,AAR044,160.770000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n44,AAR045,160.785000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n45,AAR046,160.800000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n46,AAR047,160.815000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n47,AAR048,160.830000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n48,AAR049,160.845000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n49,AAR050,160.860000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n50,AAR051,160.875000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n51,AAR052,160.890000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n52,AAR053,160.905000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n53,AAR054,160.920000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n54,AAR055,160.935000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n55,AAR056,160.950000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n56,AAR057,160.965000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n57,AAR058,160.980000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n58,AAR059,160.995000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n59,AAR060,161.010000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n60,AAR061,161.025000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n61,AAR062,161.040000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n62,AAR063,161.055000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n63,AAR064,161.070000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n64,AAR065,161.085000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n65,AAR066,161.100000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n66,AAR067,161.115000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n67,AAR068,161.130000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n68,AAR069,161.145000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n69,AAR070,161.160000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n70,AAR071,161.175000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n71,AAR072,161.190000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n72,AAR073,161.205000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n73,AAR074,161.220000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n74,AAR075,161.235000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n75,AAR076,161.250000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n76,AAR077,161.265000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n77,AAR078,161.280000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n78,AAR079,161.295000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n79,AAR080,161.310000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n80,AAR081,161.325000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n81,AAR082,161.340000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n82,AAR083,161.355000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n83,AAR084,161.370000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n84,AAR085,161.385000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n85,AAR086,161.400000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n86,AAR087,161.415000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n87,AAR088,161.430000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n88,AAR089,161.445000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n89,AAR090,161.460000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n90,AAR091,161.475000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n91,AAR092,161.490000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n92,AAR093,161.505000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n93,AAR094,161.520000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n94,AAR095,161.535000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n95,AAR096,161.550000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n96,AAR097,161.565000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n97,AAR107,160.222500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n98,AAR108,160.237500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n99,AAR109,160.252500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n100,AAR110,160.267500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n101,AAR111,160.282500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n102,AAR112,160.297500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n103,AAR113,160.312500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n104,AAR114,160.327500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n105,AAR115,160.342500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n106,AAR116,160.357500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n107,AAR117,160.372500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n108,AAR118,160.387500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n109,AAR119,160.402500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n110,AAR120,160.417500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n111,AAR121,160.432500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n112,AAR122,160.447500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n113,AAR123,160.462500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n114,AAR124,160.477500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n115,AAR125,160.492500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n116,AAR126,160.507500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n117,AAR127,160.522500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n118,AAR128,160.537500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n119,AAR129,160.552500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n120,AAR130,160.567500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n121,AAR131,160.582500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n122,AAR132,160.597500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n123,AAR133,160.612500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n124,AAR134,160.627500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n125,AAR135,160.642500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n126,AAR136,160.657500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n127,AAR137,160.672500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n128,AAR138,160.687500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n129,AAR139,160.702500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n130,AAR140,160.717500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n131,AAR141,160.732500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n132,AAR142,160.747500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n133,AAR143,160.762500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n134,AAR144,160.777500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n135,AAR145,160.792500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n136,AAR146,160.807500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n137,AAR147,160.822500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n138,AAR148,160.837500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n139,AAR149,160.852500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n140,AAR150,160.867500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n141,AAR151,160.882500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n142,AAR152,160.897500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n143,AAR153,160.912500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n144,AAR154,160.927500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n145,AAR155,160.942500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n146,AAR156,160.957500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n147,AAR157,160.972500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n148,AAR158,160.987500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n149,AAR159,161.002500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n150,AAR160,161.017500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n151,AAR161,161.032500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n152,AAR162,161.047500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n153,AAR163,161.062500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n154,AAR164,161.077500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n155,AAR165,161.092500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n156,AAR166,161.107500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n157,AAR167,161.122500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n158,AAR168,161.137500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n159,AAR169,161.152500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n160,AAR170,161.167500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n161,AAR171,161.182500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n162,AAR172,161.197500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n163,AAR173,161.212500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n164,AAR174,161.227500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n165,AAR175,161.242500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n166,AAR176,161.257500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n167,AAR177,161.272500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n168,AAR178,161.287500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n169,AAR179,161.302500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n170,AAR180,161.317500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n171,AAR181,161.332500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n172,AAR182,161.347500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n173,AAR183,161.362500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n174,AAR184,161.377500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n175,AAR185,161.392500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n176,AAR186,161.407500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n177,AAR187,161.422500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n178,AAR188,161.437500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n179,AAR189,161.452500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n180,AAR190,161.467500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n181,AAR191,161.482500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n182,AAR192,161.497500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n183,AAR193,161.512500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n184,AAR194,161.527500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n185,AAR195,161.542500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n186,AAR196,161.557500,,0.000000,,88.5,88.5,023,NN,NFM,5.00,,,,,\n',
    'US Calling Frequencies.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,6m Call,52.525000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n2,2m Call,146.520000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n3,220 Call,223.500000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n4,70cm Call,446.000000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n',
    'US FRS and GMRS Channels.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Power,Comment,URCALL,RPT1CALL,RPT2CALL\n1,FRS 1,462.562500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n2,FRS 2,462.587500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n3,FRS 3,462.612500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n4,FRS 4,462.637500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n5,FRS 5,462.662500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n6,FRS 6,462.687500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n7,FRS 7,462.712500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n8,FRS 8,467.562500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n9,FRS 9,467.587500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n10,FRS 10,467.612500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n11,FRS 11,467.637500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n12,FRS 12,467.662500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n13,FRS 13,467.687500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n14,FRS 14,467.712500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n15,FRS 15,462.550000,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n16,FRS 16,462.575000,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n17,FRS 17,462.600000,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n18,FRS 18,462.625000,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n19,FRS 19,462.650000,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n20,FRS 20,462.675000,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n21,FRS 21,462.700000,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n22,FRS 22,462.725000,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,2W,,,,\n23,GMRS 1,462.562500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,5W,,,,\n24,GMRS 2,462.587500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,5W,,,,\n25,GMRS 3,462.612500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,5W,,,,\n26,GMRS 4,462.637500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,5W,,,,\n27,GMRS 5,462.662500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,5W,,,,\n28,GMRS 6,462.687500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,5W,,,,\n29,GMRS 7,462.712500,,5.000000,,88.5,88.5,023,NN,FM,12.50,,5W,,,,\n30,GMRS 8,467.562500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n31,GMRS 9,467.587500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n32,GMRS 10,467.612500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n33,GMRS 11,467.637500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n34,GMRS 12,467.662500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n35,GMRS 13,467.687500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n36,GMRS 14,467.712500,,5.000000,,88.5,88.5,023,NN,NFM,12.50,,0.5W,,,,\n37,GMRS 15,462.550000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n38,GMRS 16,462.575000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n39,GMRS 17,462.600000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n40,GMRS 18,462.625000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n41,GMRS 19,462.650000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n42,GMRS 20,462.675000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n43,GMRS 21,462.700000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n44,GMRS 22,462.725000,,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n45,GMRS 550/15R,462.550000,+,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n46,GMRS 575/16R,462.575000,+,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n47,GMRS 600/17R,462.600000,+,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n48,GMRS 625/18R,462.625000,+,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n49,GMRS 650/19R,462.650000,+,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n50,GMRS 675/20R,462.675000,+,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n51,GMRS 700/21R,462.700000,+,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n52,GMRS 725/22R,462.725000,+,5.000000,,88.5,88.5,023,NN,FM,12.50,,50W,,,,\n',
    'US MURS Channels.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,RxDtcsCode,CrossMode,Mode,TStep,Skip,Power,Comment,URCALL,RPT1CALL,RPT2CALL,DVCODE\n1,MURS 1,151.820000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,5.00,,2.0W,,,,,\n2,MURS 2,151.880000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,5.00,,2.0W,,,,,\n3,MURS 3,151.940000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,NFM,5.00,,2.0W,,,,,\n4,Blue Dot,154.570000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,2.0W,,,,,\n5,Green Dot,154.600000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,5.00,,2.0W,,,,,\n',
    'US Marine VHF Channels.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,RxDtcsCode,CrossMode,Mode,TStep,Skip,Power,Comment,URCALL,RPT1CALL,RPT2CALL,DVCODE\n1,SEA 01,156.050000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Port Operations and Commercial,,,,\n2,SEA 05,156.250000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Port Operations.  VTS in Seattle,,,,\n3,SEA 06,156.300000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Intership Safety,,,,\n4,SEA 07,156.350000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Commercial,,,,\n5,SEA 08,156.400000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Commercial (Intership only),,,,\n6,SEA 09,156.450000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Boater Calling.  Commercial and Non-Commercial.,,,,\n7,SEA 10,156.500000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Commercial,,,,\n8,SEA 11,156.550000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Commercial.  VTS in selected areas.,,,,\n9,SEA 12,156.600000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Port Operations.  VTS in selected areas.,,,,\n10,SEA 13,156.650000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Intership Navigation Safety (Bridge-to-bridge).  Ships >20m length maintain a listening watch on this channel in US waters.,,,,\n11,SEA 14,156.700000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Port Operations.  VTS in selected areas.,,,,\n12,SEA 15,156.750000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Environmental (Receive only).  Used by Class C EPIRBs.,,,,\n13,SEA 16,156.800000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,"International Distress, Safety and Calling.  Ships required to carry radio, USCG, and most coast stations maintain a listening watch on this channel.",,,,\n14,SEA 17,156.850000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,State Control,,,,\n15,SEA 18,156.900000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Commercial,,,,\n16,SEA 19,156.950000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Commercial,,,,\n17,SEA 20,157.000000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Port Operations (duplex),,,,\n18,SEA 21,157.050000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Port Operations,,,,\n19,SEA 22,157.100000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Coast Guard Liaison and Maritime Safety Information Broadcasts. Broadcasts announced on channel 16.,,,,\n20,SEA 23,157.150000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,U.S. Government only,,,,\n21,SEA 24,157.200000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Public Correspondence (Marine Operator),,,,\n22,SEA 25,157.250000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Public Correspondence (Marine Operator),,,,\n23,SEA 26,157.300000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Public Correspondence (Marine Operator),,,,\n24,SEA 27,157.350000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Public Correspondence (Marine Operator),,,,\n25,SEA 28,157.400000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Public Correspondence (Marine Operator),,,,\n26,SEA 63,156.175000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Port Operations and Commercial. VTS in selected areas.,,,,\n27,SEA 65,156.275000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Port Operations,,,,\n28,SEA 66,156.325000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Port Operations,,,,\n29,SEA 67,156.375000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Commercial.  Used for Bridge-to-bridge communications in lower Mississippi River.  Intership only.,,,,\n30,SEA 68,156.425000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Non-Commercial-Working Channel,,,,\n31,SEA 69,156.475000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Non-Commercial,,,,\n32,DSC 70,156.525000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Digital Selective Calling (voice communications not allowed),,,,\n33,SEA 71,156.575000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Non-Commercial,,,,\n34,SEA 72,156.625000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Non-Commercial (Intership only),,,,\n35,SEA 73,156.675000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Port Operations,,,,\n36,SEA 74,156.725000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Port Operations,,,,\n37,SEA 77,156.875000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Port Operations,,,,\n38,SEA 78,156.925000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Non-Commercial,,,,\n39,SEA 79,156.975000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Commercial,,,,\n40,SEA 80,157.025000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Commercial,,,,\n41,SEA 81,157.075000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,U.S. Government only - Environmental Protection Operations,,,,\n42,SEA 82,157.125000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,U.S. Government only,,,,\n43,SEA 83,157.175000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,U.S. Government only,,,,\n44,SEA 84,157.225000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Public Correspondence (Marine Operator),,,,\n45,SEA 85,157.275000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Public Correspondence (Marine Operator),,,,\n46,SEA 86,157.325000,-,4.600000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Public Correspondence (Marine Operator),,,,\n47,SEA 87,157.375000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Public Correspondence (Marine Operator),,,,\n48,SEA 88,157.425000,-,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,Public Correspondence in selected areas only.,,,,\n49,AIS 1,161.975000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,,,,,\n50,AIS 2,162.025000,,0.000000,,88.5,88.5,023,NN,023,Tone->Tone,FM,25.00,,50W,,,,,\n',
    'US NOAA Weather Alert.csv': 'Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Skip,Comment,URCALL,RPT1CALL,RPT2CALL\n1,WX1PA7,162.550000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n2,WX2PA1,162.400000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n3,WX3PA4,162.475000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n4,WX4PA2,162.425000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n5,WX5PA3,162.450000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n6,WX6PA5,162.500000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n7,WX7PA6,162.525000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n8,WX8,161.650000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n9,WX9,161.775000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n10,WX10,163.275000,,0.000000,,88.5,88.5,023,NN,FM,5.00,,,,,\n',
}

def _stock_config_text(name):
    try:
        from importlib import resources
        item = resources.files("chirp").joinpath("stock_configs").joinpath(name)
        return item.read_text(encoding="utf-8").lstrip("\ufeff")
    except Exception:
        if name in _POCKETCHIRP_STOCK_CONFIGS:
            return _POCKETCHIRP_STOCK_CONFIGS[name]
        raise ValueError("Preset not found.")

def stock_config_catalog_json():
    """Enumerate CHIRP stock CSV files, with an embedded Android fallback."""
    names = set(_POCKETCHIRP_STOCK_CONFIGS)
    try:
        from importlib import resources
        root = resources.files("chirp").joinpath("stock_configs")
        for item in root.iterdir():
            if item.name.lower().endswith(".csv"):
                names.add(item.name)
    except Exception:
        pass
    rows = []
    for name in sorted(names):
        label = name[:-4].replace("_", " ").replace("-", " ")
        rows.append({"id": name, "label": label})
    rows.sort(key=lambda x: x["label"].lower())
    return _json.dumps(rows)

def preview_stock_config_json(filename):
    from importlib import resources
    from chirp.drivers.generic_csv import CSVRadio

    name = str(filename or "")
    if "/" in name or "\\" in name or not name.lower().endswith(".csv"):
        raise ValueError("Invalid stock configuration name.")

    text = _stock_config_text(name)

    source = CSVRadio(None)
    source.load_from(text)
    memories = [
        m for m in source.memories
        if not m.empty and _safe_int(_safe_attr(m, "freq", 0), 0) > 0
    ]
    if not memories:
        raise ValueError("This preset contains no programmed memories.")

    label = name[:-4].replace("_", " ").replace("-", " ")
    if not _last_image_bytes:
        return _build_unvalidated_import_preview(
            f"Preset: {label}",
            memories,
            metadata=[{"preset": name, "presetLocation": int(m.number)}
                      for m in memories],
            limit=1000,
        )
    return _build_import_preview(
        f"Preset: {label}",
        memories,
        source.get_features(),
        metadata=[{"preset": name, "presetLocation": int(m.number)}
                  for m in memories],
        limit=1000,
    )




















def _apply_memory_extra(mem, values):
    from chirp import settings as chirp_settings

    if not values:
        return
    wanted = {}
    if isinstance(values, dict):
        for name, value in values.items():
            wanted[(str(name), 0)] = value
    else:
        for row in values:
            if isinstance(row, dict) and row.get("name") is not None:
                wanted[(str(row["name"]), int(row.get("componentIndex", 0) or 0))] = row
    extra = _safe_attr(mem, "extra", None)
    if not extra:
        return

    seen = set()
    def walk(group):
        oid = id(group)
        if oid in seen:
            return
        seen.add(oid)
        try:
            items = list(group)
        except Exception:
            return
        for item in items:
            if isinstance(item, chirp_settings.RadioSetting):
                name = str(item.get_name())
                for component_index in [int(x) for x in item.keys()]:
                    key = (name, component_index)
                    if key not in wanted:
                        continue
                    supplied = wanted[key]
                    if isinstance(supplied, dict):
                        if supplied.get("initialized") is False:
                            continue
                        supplied = supplied.get("value")
                    value_obj = item[component_index]
                    if not value_obj.get_mutable():
                        continue
                    requested = _coerce_setting_value(value_obj, supplied)
                    value_obj.set_value(requested)
            elif isinstance(item, chirp_settings.RadioSettingGroup):
                walk(item)
    walk(extra)

def update_memory_json(memory_json):
    """Update only fields the loaded CHIRP driver says it supports."""
    data = _json.loads(memory_json)
    root_radio = _radio_from_image_bytes()
    radio, n, sub_variant = _editor_memory_target_from_data(root_radio, data)
    rf = radio.get_features()
    mem = radio.get_memory(n)

    immutable = set(_safe_attr(mem, "immutable", []) or [])

    def can(field, feature=None, default=True):
        if field in immutable:
            return False
        if feature is None:
            return default
        return _feature_bool(rf, feature, default)

    if not isinstance(n, str):
        mem.number = n
    want_empty = bool(data.get("empty", False))
    if can("empty"):
        mem.empty = want_empty

    requested_name = None
    if not want_empty:
        if "freq" not in immutable and "freq" in data:
            mem.freq = int(round(float(data["freq"]) * 1_000_000))

        if can("name", "has_name", True) and "name" in data:
            limit = _safe_int(_safe_attr(rf, "valid_name_length", 0), 0)
            text = _normalize_case_to_charset(
                str(data.get("name", "")),
                _feature_valid_characters_text(rf),
            )
            requested_name = text[:limit] if limit > 0 else text
            mem.name = requested_name

        if "duplex" not in immutable and "duplex" in data:
            mem.duplex = str(data.get("duplex", ""))

        if can("offset", "has_offset", True) and "offset" in data:
            mem.offset = int(round(float(data.get("offset", 0)) * 1_000_000))

        if "tmode" not in immutable and "tmode" in data:
            mem.tmode = str(data.get("tmode", ""))

        if "rtone" not in immutable and "rtone" in data and data.get("rtone") is not None:
            mem.rtone = float(data["rtone"])

        if can("ctone", "has_ctone", False) and "ctone" in data and data.get("ctone") is not None:
            mem.ctone = float(data["ctone"])

        if can("dtcs", "has_dtcs", True) and "dtcs" in data and data.get("dtcs") is not None:
            mem.dtcs = int(data["dtcs"])

        if can("rx_dtcs", "has_rx_dtcs", False) and "rx_dtcs" in data and data.get("rx_dtcs") is not None:
            mem.rx_dtcs = int(data["rx_dtcs"])

        if can("dtcs_polarity", "has_dtcs_polarity", False) and "dtcs_polarity" in data:
            mem.dtcs_polarity = str(data.get("dtcs_polarity", "NN"))

        if can("cross_mode", "has_cross", False) and "cross_mode" in data:
            mem.cross_mode = str(data.get("cross_mode", "Tone->Tone"))

        if can("mode", "has_mode", True) and "mode" in data:
            mem.mode = str(data.get("mode", "FM"))

        if "skip" not in immutable and "skip" in data:
            mem.skip = str(data.get("skip", ""))

        if can("tuning_step", "has_tuning_step", False) and "tuning_step" in data and data.get("tuning_step") is not None:
            mem.tuning_step = float(data["tuning_step"])

        if can("comment", "has_comment", False) and "comment" in data:
            mem.comment = str(data.get("comment", ""))

        if "power" not in immutable and "power" in data:
            p = str(data.get("power", ""))
            if p:
                for level in (_feature_seq(rf, "valid_power_levels")):
                    if str(level) == p:
                        mem.power = level
                        break

        for field in ("dv_urcall", "dv_rpt1call", "dv_rpt2call", "dv_code"):
            if field in data and hasattr(mem, field) and field not in immutable:
                setattr(mem, field, int(data[field]) if field == "dv_code" else str(data[field]))
        if "extra" in data:
            _apply_memory_extra(mem, data.get("extra"))

    problems = radio.validate_memory(mem)
    errors = [
        str(x) for x in problems
        if x.__class__.__name__ == "ValidationError"
    ]
    if errors:
        raise ValueError("; ".join(errors))

    radio.check_set_memory_immutable_policy(radio.get_memory(n), mem)
    radio.set_memory(mem)

    # Some drivers advertise a broad/default valid_characters set even though
    # their actual image encoder only has uppercase glyph codes. In that case
    # lowercase passes validation but set_memory() silently stores blanks.
    # Detect the driver's real behavior from its own in-memory round trip and
    # retry uppercase only when that fixes the loss.
    if requested_name is not None and _has_lowercase_text(requested_name):
        stored_name = _radio_text_for_compare(
            _safe_attr(radio.get_memory(n), "name", "")
        )
        wanted_name = _radio_text_for_compare(requested_name)
        if stored_name != wanted_name:
            uppercase_name = str(requested_name).upper()
            if uppercase_name != requested_name:
                mem.name = uppercase_name
                retry_problems = radio.validate_memory(mem)
                retry_errors = [
                    str(x) for x in retry_problems
                    if x.__class__.__name__ == "ValidationError"
                ]
                if not retry_errors:
                    radio.set_memory(mem)
                    uppercase_stored = _radio_text_for_compare(
                        _safe_attr(radio.get_memory(n), "name", "")
                    )
                    if uppercase_stored != _radio_text_for_compare(uppercase_name):
                        raise ValueError(
                            "Driver cannot preserve channel name %r; lowercase was "
                            "lost and uppercase retry read back as %r."
                            % (requested_name, uppercase_stored)
                        )
                    LOG.info(
                        "PocketCHIRP normalized channel name to uppercase after "
                        "driver round-trip loss: %r -> %r",
                        requested_name, uppercase_name)
                else:
                    raise ValueError("; ".join(retry_errors))

    _save_working_radio(root_radio)
    return pocketchirp_radio_document_json()



def _editor_memory_target_from_id(root_radio, memory_id):
    """Resolve a stable editor memoryId without relying on flattened display numbering."""
    text = str(memory_id or "")
    if text.startswith("view:") and ":number:" in text:
        try:
            left, native_text = text.rsplit(":number:", 1)
            view_index = int(left.split(":", 2)[1])
            native_number = int(native_text)
            views = _editor_radio_views(root_radio)
            if view_index < 0 or view_index >= len(views):
                raise ValueError("Memory references an unknown radio sub-device.")
            view, _dlo, _dhi, nlo, nhi, variant = views[view_index]
            if native_number < int(nlo) or native_number > int(nhi):
                raise ValueError("Memory is outside this radio sub-device's range.")
            return view, native_number, variant
        except ValueError:
            raise
        except Exception:
            pass
    try:
        return _editor_memory_target(root_radio, int(text))
    except Exception:
        raise ValueError("Unknown memory selection: " + text)


def delete_memories_json(memory_ids_json="[]", delete_all=False):
    """Clear selected or all programmed ordinary memories in one undoable mutation."""
    import copy as _copy

    if not _last_image_bytes:
        raise ValueError("Read a radio or load a .img before deleting channels.")

    root_radio = _radio_from_image_bytes()
    targets = []

    if bool(delete_all):
        for view_index, (view, _dlo, _dhi, nlo, nhi, _variant) in enumerate(_editor_radio_views(root_radio)):
            for native_number in range(int(nlo), int(nhi) + 1):
                try:
                    current = view.get_memory(native_number)
                except Exception:
                    continue
                if bool(_safe_attr(current, "empty", False)):
                    continue
                targets.append((view, native_number, f"view:{view_index}:number:{native_number}"))
    else:
        ids = _json.loads(memory_ids_json) if isinstance(memory_ids_json, str) else memory_ids_json
        seen = set()
        for memory_id in (ids or []):
            key = str(memory_id or "")
            if not key or key in seen or ":special:" in key:
                continue
            seen.add(key)
            view, native_number, _variant = _editor_memory_target_from_id(root_radio, key)
            targets.append((view, int(native_number), key))

    if not targets:
        raise ValueError("No programmed ordinary channels were selected.")

    deleted = 0
    skipped = []
    for view, native_number, key in targets:
        try:
            old = view.get_memory(native_number)
            if bool(_safe_attr(old, "empty", False)):
                continue
            try:
                mem = _copy.deepcopy(old)
            except Exception:
                mem = old
            immutable = set(_safe_attr(old, "immutable", []) or [])
            if "empty" in immutable:
                skipped.append(key)
                continue
            mem.empty = True
            view.check_set_memory_immutable_policy(old, mem)
            view.set_memory(mem)
            deleted += 1
        except Exception as exc:
            skipped.append(f"{key}: {exc}")

    if deleted <= 0:
        detail = "; ".join(skipped[:3])
        raise ValueError("No channels could be deleted." + (" " + detail if detail else ""))

    _save_working_radio(root_radio)
    return _json.dumps({
        "deleted": deleted,
        "skipped": skipped,
        "all": bool(delete_all),
        "state": _json.loads(pocketchirp_radio_document_json()),
    })


def preview_image_conversion_bytes(source_bytes):
    """Preview portable channel conversion from raw source-image bytes."""
    if not _last_image_bytes:
        raise ValueError("Read the target radio or load its .img before converting another image.")

    source_bytes = bytes(source_bytes or b"")
    if not source_bytes:
        raise ValueError("The selected source image is empty.")

    _raw, metadata = _metadata_for_image(source_bytes)
    entry = _entry_for_metadata(metadata)
    if entry is None:
        raise ValueError(
            "PocketCHIRP could not identify the source image's radio driver. "
            "Use a CHIRP/PocketCHIRP .img containing radio metadata."
        )

    source_radio = _radio_from_image_bytes(source_bytes)
    source_name = (
        f"{getattr(source_radio, 'VENDOR', '')} {getattr(source_radio, 'MODEL', '')}"
        + (f" {getattr(source_radio, 'VARIANT', '')}" if getattr(source_radio, "VARIANT", "") else "")
    ).strip() or "Source Radio"

    memories = []
    source_features = []
    metadata_rows = []
    for view, dlo, dhi, nlo, nhi, variant in _editor_radio_views(source_radio):
        view_features = view.get_features()
        for display_number in range(int(dlo), int(dhi) + 1):
            native_number = int(nlo) + (display_number - int(dlo))
            try:
                mem = view.get_memory(native_number)
            except Exception:
                continue
            if bool(_safe_attr(mem, "empty", False)):
                continue
            portable = _portable_memory_copy(mem, len(memories))
            memories.append(portable)
            source_features.append(view_features)
            metadata_rows.append({
                "sourceRadio": source_name,
                "sourceChannel": display_number,
                "sourceSubDevice": str(variant or ""),
            })

    if not memories:
        raise ValueError("The source image contains no programmed ordinary channels.")

    return _build_import_preview(
        "Image: " + source_name,
        memories,
        source_features,
        metadata=metadata_rows,
        limit=10000,
    )



def _coerce_setting_value(value, supplied):
    """Coerce according to one CHIRP RadioSettingValue subclass."""
    cls = value.__class__.__name__
    if "Boolean" in cls:
        if isinstance(supplied, str):
            return supplied.strip().lower() in ("1", "true", "yes", "on")
        return bool(supplied)
    if "Integer" in cls:
        return int(supplied)
    if "Float" in cls:
        return float(supplied)
    # RadioSettingValueList and RadioSettingValueMap intentionally accept their
    # user-facing option string. String values also honor a driver-declared
    # character set: if lowercase is forbidden but the uppercase counterpart is
    # allowed, normalize the case before CHIRP validates/autopads the value.
    text = str(supplied)
    return _normalize_case_to_charset(text, _charset_text(value))

def _setting_values_equivalent(a, b, kind):
    if kind == "number":
        try:
            return abs(float(a) - float(b)) <= 1e-9
        except Exception:
            return False
    return a == b


def _setting_changes_from_json(setting_json):
    """Decode one PocketCHIRP settings request into CHIRP-neutral changes."""
    data = _json.loads(setting_json)
    raw_changes = data.get("changes") if isinstance(data, dict) else None
    if raw_changes is None:
        # Backward compatibility with older editors which send one setting.
        raw_changes = [data]
    if not isinstance(raw_changes, list) or not raw_changes:
        raise ValueError("No radio setting changes were supplied")
    for change in raw_changes:
        if not isinstance(change, dict):
            raise ValueError("Invalid radio setting change")
    return raw_changes


def _prune_uninitialized_immutable_settings(root):
    """Mirror CHIRP wxui SettingsEdit._remove_dead_settings().

    Desktop CHIRP does not pass immutable or uninitialized RadioSetting values
    to a driver's set_settings(). Some drivers (including KG-UV8E) convert
    every received value with int()/float() and will crash on an untouched
    uninitialized value whose backing value is None.
    """
    from chirp import settings as chirp_settings

    removed = []

    def walk(group):
        # CHIRP's values() returns a stable list-like snapshot, but force list()
        # so deletion during traversal is safe across CHIRP versions.
        try:
            children = list(group.values())
        except Exception:
            children = list(group)
        for element in children:
            if isinstance(element, chirp_settings.RadioSetting):
                drop = False
                reason = ""
                for value in element:
                    if not value.get_mutable():
                        drop = True
                        reason = "immutable"
                        break
                    if not bool(_safe_attr(value, "initialized", True)):
                        drop = True
                        reason = "uninitialized"
                        break
                if drop:
                    removed.append((str(element.get_name()), reason))
                    try:
                        del group[element]
                    except Exception:
                        # Match the intent of desktop CHIRP even if a future
                        # container implementation exposes remove() instead.
                        remover = getattr(group, "remove", None)
                        if callable(remover):
                            remover(element)
                        else:
                            raise
            elif isinstance(element, chirp_settings.RadioSettingGroup):
                walk(element)

    walk(root)
    return removed


def _apply_setting_changes_json(setting_json, return_document=True, _allow_case_retry=True):
    """Apply one desktop-CHIRP-style RadioSettings transaction.

    Save/Write materialization calls this with return_document=False so replaying
    a settings journal never builds a huge Radio Document that is immediately
    discarded.  Interactive legacy callers retain the historical document
    return value.
    """
    global _last_image_bytes, _last_raw_bytes, _last_hash_info

    raw_changes = _setting_changes_from_json(setting_json)

    old_image = _last_image_bytes
    old_raw = _last_raw_bytes
    old_hash_info = _last_hash_info

    radio = _radio_from_image_bytes()
    settings = radio.get_settings()
    if settings is None:
        raise ValueError("This radio driver does not expose editable settings")

    applied = []
    seen_ids = set()
    try:
        # Stage every change onto the SAME CHIRP RadioSettings tree before the
        # driver sees it. This preserves callbacks, cross-setting dependencies,
        # and RadioSettingValue.changed() semantics like desktop CHIRP.
        for change in raw_changes:
            target_name = str(change.get("name", ""))
            target_id = str(change.get("id", "") or "")
            if not target_name:
                raise ValueError("Radio setting name is missing")
            dedupe_key = target_id or ("name:" + target_name)
            if dedupe_key in seen_ids:
                raise ValueError("Radio setting was supplied more than once: " + target_name)
            seen_ids.add(dedupe_key)

            found, component_index, value_obj = _resolve_setting(
                settings, target_id, target_name)
            if not value_obj.get_mutable():
                raise ValueError("This setting is read-only: " + target_name)

            kind = str(change.get("kind", "string"))
            before_value = _setting_value_for_ui(value_obj)
            requested = _coerce_setting_value(value_obj, change.get("value"))

            # CHIRP's value object owns validation, maps/lists, character sets,
            # ranges, mutability, and the changed() flag.
            value_obj.set_value(requested)
            expected_value = _setting_value_for_ui(value_obj)
            applied.append({
                "id": target_id,
                "name": target_name,
                "kind": kind,
                "before": before_value,
                "expected": expected_value,
            })

        # Desktop CHIRP removes immutable and uninitialized values before
        # calling the driver. This is essential for drivers such as KG-UV8E,
        # which walk the entire supplied tree and may call int(None) on an
        # untouched uninitialized frequency field.
        pruned_settings = _prune_uninitialized_immutable_settings(settings)

        # One complete, CHIRP-sanitized tree, one driver call.
        try:
            radio.set_settings(settings)
        except Exception as exc:
            names = ", ".join(row["name"] for row in applied)
            raise ValueError(
                "CHIRP driver rejected radio setting change(s) %s: %s: %s"
                % (names or "(unknown)", exc.__class__.__name__, exc)) from exc
        _save_working_radio(radio)
        if not _last_image_bytes:
            names = ", ".join(row["name"] for row in applied)
            raise ValueError(
                "CHIRP driver produced an empty image after setting change(s): " + names)

        # Re-open exactly what would be written and verify EVERY staged setting.
        verify_radio = _radio_from_image_bytes()
        verify_settings = verify_radio.get_settings()
        if verify_settings is None:
            raise ValueError("Driver could not read settings back from the saved image")

        failures = []
        failed_rows = []
        for row in applied:
            _verify_setting, _verify_index, verify_value = _resolve_setting(
                verify_settings, row["id"], row["name"])
            actual_value = _setting_value_for_ui(verify_value)
            if not _setting_values_equivalent(row["expected"], actual_value, row["kind"]):
                failures.append(
                    "%s (requested %r, read back %r)" %
                    (row["name"], row["expected"], actual_value))
                failed_rows.append((row, actual_value))
        if failures:
            # A few drivers expose string settings whose value object/default
            # charset accepts lowercase even though the driver's image encoder
            # does not. Retry ONLY failed lowercase string values, from the
            # original pre-edit image, and only once.
            retry_keys = set()
            if _allow_case_retry:
                for row, _actual in failed_rows:
                    expected = row.get("expected")
                    if (row.get("kind") == "string"
                            and isinstance(expected, str)
                            and _has_lowercase_text(expected)
                            and expected.upper() != expected):
                        retry_keys.add(row.get("id") or ("name:" + row.get("name", "")))

            if retry_keys:
                retry_changes = []
                for change in raw_changes:
                    retry = dict(change)
                    key = str(retry.get("id", "") or "") or (
                        "name:" + str(retry.get("name", "")))
                    value = retry.get("value")
                    if key in retry_keys and isinstance(value, str):
                        retry["value"] = value.upper()
                    retry_changes.append(retry)

                # Restore the exact image that existed before this settings
                # transaction, then replay the complete batch with only the
                # proven-failing lowercase strings uppercased.
                _last_image_bytes = old_image
                _last_raw_bytes = old_raw
                _last_hash_info = old_hash_info
                LOG.info(
                    "PocketCHIRP retrying %d radio setting string(s) as uppercase "
                    "after driver round-trip loss", len(retry_keys))
                return _apply_setting_changes_json(
                    _json.dumps({"changes": retry_changes}, separators=(",", ":")),
                    return_document=return_document,
                    _allow_case_retry=False)

            raise ValueError("Driver did not preserve setting change(s): " + "; ".join(failures))

        genuinely_changed = any(row["before"] != row["expected"] for row in applied)
        if genuinely_changed and _last_raw_bytes == old_raw:
            names = ", ".join(row["name"] for row in applied if row["before"] != row["expected"])
            raise ValueError(
                "Driver accepted the setting change(s) but the radio image did not change: " + names)

        if return_document:
            return pocketchirp_radio_document_json()
        return _json.dumps({
            "applied": len(applied),
            "names": [row["name"] for row in applied],
            "rawChanged": bool(_last_raw_bytes != old_raw),
            "rawSha256": hashlib.sha256(_last_raw_bytes).hexdigest(),
        }, separators=(",", ":"))
    except Exception:
        _last_image_bytes = old_image
        _last_raw_bytes = old_raw
        _last_hash_info = old_hash_info
        raise


def update_setting_json(setting_json):
    return _apply_setting_changes_json(setting_json, return_document=True)



# ===========================================================================
# PocketCHIRP Stage 5 PREBUILT catalog / lazy bundled driver loader
#
# radio_catalog.json is an Android asset generated BEFORE the APK is packaged.
# The phone does not scan or build a radio catalog.
# ===========================================================================
import importlib as _importlib
import sys as _sys
import types as _types

_radio_catalog_cache = None
_radio_catalog_by_key = {}
_selected_radio_key = None
_selected_radio_class = None

_custom_radio_classes = {}
_custom_driver_entries = {}
_custom_driver_modules = {}


def _custom_entry_for_runtime_radio(radio):
    """Return the exact loaded custom-driver entry for a runtime radio.

    Runtime custom drivers are intentionally outside CHIRP's global registry.
    Public VENDOR/MODEL/VARIANT therefore cannot be the parser identity. Match
    the actual runtime class to PocketCHIRP's loaded custom-driver table.
    """
    if radio is None:
        return None
    runtime_cls = _unwrap_runtime_class(radio.__class__)

    selected = _custom_driver_entries.get(_selected_radio_key) if _selected_radio_key else None
    if selected is not None:
        selected_cls = _custom_radio_classes.get(selected.get("key"))
        if isinstance(selected_cls, type) and _unwrap_runtime_class(selected_cls) is runtime_cls:
            return selected

    matches = []
    for key, cls in (_custom_radio_classes or {}).items():
        if isinstance(cls, type) and _unwrap_runtime_class(cls) is runtime_cls:
            entry = _custom_driver_entries.get(key)
            if entry is not None:
                matches.append(entry)
    return matches[0] if len(matches) == 1 else None


def _stamp_custom_image_metadata(radio):
    """Persist exact custom-parser identity in CHIRP's extensible .img metadata.

    These fields live after CHIRP's MAGIC marker and never alter the raw radio
    payload. CHIRP preserves arbitrary metadata keys across load/save while it
    refreshes its own standard rclass/vendor/model/variant/chirp_version keys.
    """
    entry = _custom_entry_for_runtime_radio(radio)
    if entry is None:
        return False

    radio.metadata = {
        "pocketchirp_custom_driver_key": str(entry.get("key") or ""),
        "pocketchirp_custom_driver_sha256": str(entry.get("sha256") or ""),
        "pocketchirp_custom_driver_class": str(entry.get("class") or ""),
    }
    return True


# ---------------------------------------------------------------------------
# Universal runtime custom-driver policy
# ---------------------------------------------------------------------------
# Applies to every CHIRP driver module loaded at runtime:
#   * retain every registered radio class; there is no model/variant count cap
#   * preserve VENDOR + MODEL + VARIANT as the user's exact public selection
#   * never select the first entry of a multi-radio module by registration order
#   * preserve a unique prior exact selection, or auto-select only a 1-entry file
#   * detect split identification/download clone lifecycles structurally across
#     the selected class's complete inheritance chain
#   * never silently replace a selected class with a sibling variant during a
#     normal read/write operation
#
# Auto-detection remains separate and may discover a model. Once the user has
# explicitly selected a radio, normal cloning is exact-selection driven.

def _custom_public_identity(entry_or_cls):
    """Normalized (vendor, model, variant) for either a catalog entry or class."""
    if isinstance(entry_or_cls, dict):
        return (
            str(entry_or_cls.get("vendor", "") or "").strip(),
            str(entry_or_cls.get("model", "") or "").strip(),
            str(entry_or_cls.get("variant", "") or "").strip(),
        )
    return (
        str(getattr(entry_or_cls, "VENDOR", "") or "").strip(),
        str(getattr(entry_or_cls, "MODEL", "") or "").strip(),
        str(getattr(entry_or_cls, "VARIANT", "") or "").strip(),
    )


def _fold_radio_identity(identity):
    if identity is None:
        return None
    try:
        return tuple(str(x or "").strip().casefold() for x in identity)
    except Exception:
        return None


def _unique_custom_entry_for_identity(entries, identity):
    folded = _fold_radio_identity(identity)
    if folded is None:
        return None
    matches = [
        e for e in entries
        if _fold_radio_identity(_custom_public_identity(e)) == folded
    ]
    return matches[0] if len(matches) == 1 else None


def _choose_custom_driver_entry(entries, select_loaded, previous_key=None,
                                previous_identity=None):
    """Choose only when selection is unambiguous; never guess from list order."""
    if not bool(select_loaded):
        return None

    if previous_key:
        exact_key = next((e for e in entries if e.get("key") == previous_key), None)
        if exact_key is not None:
            return exact_key

    exact_identity = _unique_custom_entry_for_identity(entries, previous_identity)
    if exact_identity is not None:
        return exact_identity

    return entries[0] if len(entries) == 1 else None


def _build_bundled_catalog_from_chirp():
    """Build the bundled-radio catalog from the CHIRP copy inside this GPL APK.

    LICENSE/ARCHITECTURE BOUNDARY:
    The proprietary PocketCHIRP APK no longer bundles or generates CHIRP's radio
    catalog.  This engine imports its own bundled CHIRP drivers, then publishes
    only neutral radio identity/mapping records across IPC.
    """
    from chirp import directory

    # CHIRP's own loader is authoritative for which bundled drivers actually
    # import in this engine build. It intentionally continues past individual
    # import failures, matching desktop CHIRP's registration model.
    directory.import_drivers()

    entries = []
    seen = set()
    modules = set()

    def add_entry(module, class_name, vendor, model, variant="", kind="driver",
                  parent_class=""):
        vendor = str(vendor or "").strip()
        model = str(model or "").strip()
        variant = str(variant or "").strip()
        if not vendor or not model:
            return
        # Match the historical catalog generator exactly: public-identity
        # duplicate detection is case-sensitive, while final sorting is not.
        signature = (vendor, model, variant)
        if signature in seen:
            return
        seen.add(signature)
        modules.add(str(module or ""))
        entries.append({
            "module": str(module or ""),
            "class": str(class_name or ""),
            "parentClass": str(parent_class or ""),
            "vendor": vendor,
            "model": model,
            "variant": variant,
            "kind": str(kind or "driver"),
        })

    for cls in list(directory.DRV_TO_RADIO.values()):
        if not isinstance(cls, type):
            continue
        # CHIRP explicitly marks detected/minor variants which should not be
        # offered as independent user choices. Preserve that upstream policy.
        if getattr(cls, "_DETECTED_BY", None) is not None:
            continue
        if bool(getattr(cls, "_MINOR_VARIANT", False)):
            continue

        module_full = str(getattr(cls, "__module__", "") or "")
        if not module_full.startswith("chirp.drivers."):
            continue
        module = module_full.rsplit(".", 1)[-1]
        add_entry(module, getattr(cls, "__name__", ""),
                  getattr(cls, "VENDOR", ""), getattr(cls, "MODEL", ""),
                  getattr(cls, "VARIANT", ""), "driver")

        # Python ALIASES are CHIRP-owned marketed identities which execute the
        # parent registered driver. Keep the same mapping fields the historical
        # prebuilt catalog used so _find_loaded_radio_class remains exact.
        for alias in list(getattr(cls, "ALIASES", []) or []):
            if not isinstance(alias, type):
                continue
            # The old build-time generator included Python aliases declared in
            # the same driver module. Keep that exact rule so stable catalog keys
            # remain compatible with existing saved selections.
            if str(getattr(alias, "__module__", "") or "") != module_full:
                continue
            add_entry(module, getattr(alias, "__name__", ""),
                      getattr(alias, "VENDOR", ""), getattr(alias, "MODEL", ""),
                      getattr(alias, "VARIANT", ""), "alias",
                      getattr(cls, "__name__", ""))

    # CHIRP also publishes marketed/compatibility names in
    # chirp/share/model_alias_map.yaml. These are NOT Python ALIASES and
    # therefore are absent from directory.DRV_TO_RADIO. The engine-side catalog
    # must merge them explicitly or marketed radios such as the Baofeng AR-5RM
    # disappear from PocketCHIRP even though their executable driver (5RM) is
    # still present.
    #
    # Keep this engine-owned: it only reflects data shipped by the GPL CHIRP
    # package and changes no transport or radio protocol behavior.
    try:
        import chirp as _chirp_pkg

        # The Android Chaquopy build stores Python sources/resources inside
        # assets/chaquopy/app.imy.  A pathlib path derived from chirp.__file__
        # therefore is not necessarily a real filesystem path.  Read the CHIRP
        # package resource through importlib.resources first (works for zip/IMY
        # package loaders), then pkgutil, and use pathlib only as a final desktop
        # fallback.  All three paths are standard-library-only.
        _alias_text = None
        try:
            from importlib import resources as _resources
            _alias_text = (
                _resources.files(_chirp_pkg)
                .joinpath("share")
                .joinpath("model_alias_map.yaml")
                .read_text(encoding="utf-8-sig")
            )
        except Exception:
            try:
                import pkgutil as _pkgutil
                _alias_bytes = _pkgutil.get_data(
                    _chirp_pkg.__name__, "share/model_alias_map.yaml")
                if _alias_bytes is not None:
                    _alias_text = _alias_bytes.decode("utf-8-sig")
            except Exception:
                _alias_text = None

        if _alias_text is None:
            import pathlib as _pathlib
            _alias_path = (_pathlib.Path(_chirp_pkg.__file__).resolve().parent /
                           "share" / "model_alias_map.yaml")
            with _alias_path.open("r", encoding="utf-8-sig") as _f:
                _alias_text = _f.read()

        # Desktop/development Python may have PyYAML, but the Android Chaquopy
        # engine intentionally ships no pip dependencies.  model_alias_map.yaml
        # uses a deliberately small YAML subset (top-level vendor keys followed
        # by list records containing alt/model/variant).  Prefer PyYAML when it
        # is available, and otherwise parse that exact upstream subset using only
        # the Python standard library.  This keeps marketed aliases such as
        # Baofeng AR-5RM visible on Android without adding any transport/runtime
        # dependency or changing CHIRP driver behavior.
        try:
            import yaml as _yaml
            _alias_map = _yaml.load(_alias_text, Loader=_yaml.FullLoader) or {}
        except Exception:
            def _alias_scalar(_value):
                _value = str(_value or "").strip()
                if len(_value) >= 2 and _value[0] == _value[-1] and _value[0] in ("'", '"'):
                    _quote = _value[0]
                    _value = _value[1:-1]
                    if _quote == "'":
                        _value = _value.replace("''", "'")
                    else:
                        _value = bytes(_value, "utf-8").decode("unicode_escape")
                return _value

            _alias_map = {}
            _vendor_group = None
            _record = None
            for _raw_line in _alias_text.splitlines():
                if not _raw_line.strip() or _raw_line.lstrip().startswith("#"):
                    continue
                if not _raw_line[0].isspace() and not _raw_line.startswith("-") and _raw_line.rstrip().endswith(":"):
                    _vendor_group = _alias_scalar(_raw_line.rstrip()[:-1])
                    _alias_map.setdefault(_vendor_group, [])
                    _record = None
                    continue
                _stripped = _raw_line.strip()
                if _stripped.startswith("- "):
                    if _vendor_group is None:
                        continue
                    _field = _stripped[2:]
                    if ":" not in _field:
                        continue
                    _key, _value = _field.split(":", 1)
                    _record = {_key.strip(): _alias_scalar(_value)}
                    _alias_map[_vendor_group].append(_record)
                    continue
                if _record is not None and ":" in _stripped:
                    _key, _value = _stripped.split(":", 1)
                    _record[_key.strip()] = _alias_scalar(_value)

        _pending = []
        for _vendor_group, _models in _alias_map.items():
            _display_vendor = str(_vendor_group or "").split("/", 1)[0].strip()
            for _item in (_models or []):
                _display_model = str(_item.get("model", "") or "").strip()
                _variant = str(_item.get("variant", "") or "").strip()
                _alt = str(_item.get("alt", "") or "").strip()
                if not _display_vendor or not _display_model or not _alt:
                    continue

                # CHIRP's map contains a few model labels that redundantly carry
                # their vendor prefix (notably "Baofeng AR-5RM"). PocketCHIRP
                # already displays the vendor separately, and older PocketCHIRP
                # AR-5RM images were stamped MODEL="AR-5RM". Normalize only an
                # exact leading vendor token so the public identity stays stable.
                _prefix = _display_vendor + " "
                if _display_model.casefold().startswith(_prefix.casefold()):
                    _display_model = _display_model[len(_prefix):].strip()

                _pending.append({
                    "vendor": _display_vendor,
                    "model": _display_model,
                    "variant": _variant,
                    "alt": _alt,
                })

        # Resolve aliases iteratively because CHIRP permits aliases to point to
        # other aliases. Match the same vendor/model(+variant) forms used by the
        # historical development-PC generator.
        _progress = True
        while _pending and _progress:
            _progress = False
            _next_pending = []
            for _item in _pending:
                _vendor = _item["vendor"]
                _alt = _item["alt"]
                if " " in _alt:
                    _alt_vendor, _alt_model = _alt.split(" ", 1)
                else:
                    _alt_vendor, _alt_model = _vendor, _alt

                _target = None
                for _e in entries:
                    if (_e.get("vendor") == _alt_vendor and
                            _e.get("model") == _alt_model and
                            not (_e.get("variant") or "")):
                        _target = _e
                        break

                if _target is None:
                    _candidates = [
                        _e for _e in entries
                        if _e.get("vendor") == _alt_vendor and
                        (str(_e.get("model") or "") +
                         str(_e.get("variant") or "")) == _alt_model
                    ]
                    if len(_candidates) == 1:
                        _target = _candidates[0]

                if _target is None:
                    _candidates = [
                        _e for _e in entries
                        if _e.get("vendor") == _alt_vendor and
                        _e.get("model") == _alt_model
                    ]
                    if len(_candidates) == 1:
                        _target = _candidates[0]

                if _target is None:
                    _next_pending.append(_item)
                    continue

                # Preserve the target's public/alias class name for stable
                # catalog identity, but carry its registered parent backend
                # through alias chains. Some model_alias_map rows point at a
                # CHIRP Alias class (label-only, not a Radio); the executable
                # backend in that case is the target alias entry's parentClass.
                add_entry(
                    _target.get("module", ""),
                    _target.get("class", ""),
                    _item["vendor"],
                    _item["model"],
                    _item["variant"],
                    "map-alias",
                    (_target.get("parentClass", "") or
                     _target.get("class", "")),
                )
                _progress = True

            _pending = _next_pending
    except Exception as _alias_exc:
        # A missing/broken alias map must not take down the entire CHIRP engine;
        # canonical registered drivers remain usable. Surface the problem in the
        # engine log so update validation can catch it.
        try:
            LOG.warning("Could not merge CHIRP model alias map: %s", _alias_exc)
        except Exception:
            pass

    entries.sort(key=lambda x: (
        x["vendor"].casefold(), x["model"].casefold(), x["variant"].casefold()))
    for index, entry in enumerate(entries):
        entry["key"] = "%s:%s:%s:%d" % (
            entry["module"], entry["class"], entry["kind"], index)
        entry["publicIdentity"] = {
            "vendor": entry["vendor"],
            "model": entry["model"],
            "variant": entry["variant"],
        }

    # Custom CHIRP drivers are runtime registrations and are merged only on the
    # engine side. Their files/catalog/search lifecycle remains app-owned.
    entries.extend(list(_custom_driver_entries.values()))
    return {
        "formatVersion": 1,
        "offline": True,
        "generated": True,
        "generatedBy": "PocketCHIRP CHIRP Engine",
        "loadedCount": len(entries),
        "sourceModules": len([x for x in modules if x]),
        "selectedKey": None,
        "customDriverCount": len(_custom_driver_entries),
        "radios": entries,
    }


def _ensure_radio_catalog():
    global _radio_catalog_cache, _radio_catalog_by_key
    if _radio_catalog_cache is None:
        _radio_catalog_cache = _build_bundled_catalog_from_chirp()
        _radio_catalog_by_key = {
            x["key"]: x for x in (_radio_catalog_cache.get("radios") or [])}
    return _radio_catalog_cache


def radio_catalog_json():
    """Return the neutral catalog generated by this GPL engine's CHIRP copy."""
    return _json.dumps(_ensure_radio_catalog(), separators=(",", ":"))



def _refresh_catalog_with_custom_entries():
    """Merge runtime custom entries into the current prebuilt catalog."""
    global _radio_catalog_by_key
    if _radio_catalog_cache is None:
        return
    radios = [
        x for x in (_radio_catalog_cache.get("radios") or [])
        if not x.get("customDriver")
    ]
    radios.extend(_custom_driver_entries.values())
    _radio_catalog_cache["radios"] = radios
    _radio_catalog_cache["loadedCount"] = len(radios)
    _radio_catalog_cache["customDriverCount"] = len(_custom_driver_entries)
    _radio_catalog_by_key = {x["key"]: x for x in radios}


def _custom_driver_classes_from_module(module_obj, directory):
    """Return ALL radio classes actually defined by a loaded custom module.

    There is deliberately no model/variant count limit. A custom driver may
    register one radio, three variants, eighteen related models, or hundreds.
    Every class CHIRP registers from that module remains independently selectable.
    """
    from chirp import chirp_common

    registered = []
    seen = set()

    # Prefer classes CHIRP itself registered while the file executed.
    for cls in list(directory.DRV_TO_RADIO.values()):
        if (isinstance(cls, type)
                and getattr(cls, "__module__", "") == module_obj.__name__
                and cls not in seen):
            registered.append(cls)
            seen.add(cls)

    # A development file should normally use @directory.register, but still
    # recognize a directly-defined Radio subclass so the error is useful.
    if not registered:
        for obj in module_obj.__dict__.values():
            if not isinstance(obj, type) or obj in seen:
                continue
            if getattr(obj, "__module__", "") != module_obj.__name__:
                continue
            try:
                is_radio = issubclass(obj, chirp_common.Radio)
            except Exception:
                is_radio = False
            if is_radio and getattr(obj, "VENDOR", None) and getattr(obj, "MODEL", None):
                registered.append(obj)
                seen.add(obj)

    return registered




def _compile_custom_driver_source(source_bytes, filename):
    """Compile a trusted custom driver while removing only top-level wx imports.

    Android PocketCHIRP intentionally does not ship wxPython. Desktop-only wx
    imports are common in development drivers even when their radio protocol
    code does not otherwise use wx. Only module-level imports are rewritten;
    imports inside functions/classes are preserved so real runtime wx use still
    fails normally instead of being silently hidden. Mixed imports retain all
    non-wx names.
    """
    import ast as _ast
    if isinstance(source_bytes, bytes):
        source = source_bytes.decode("utf-8-sig")
    else:
        source = str(source_bytes)
    tree = _ast.parse(source, filename=filename)
    body = []
    for node in tree.body:
        if isinstance(node, _ast.Import):
            kept = [alias for alias in node.names
                    if not (alias.name == "wx" or alias.name.startswith("wx."))]
            if not kept:
                continue
            if len(kept) != len(node.names):
                node.names = kept
        elif isinstance(node, _ast.ImportFrom):
            mod = node.module or ""
            if mod == "wx" or mod.startswith("wx."):
                continue
        body.append(node)
    tree.body = body
    _ast.fix_missing_locations(tree)
    return compile(tree, filename, "exec")

def load_custom_driver_source_json(source_text, filename, select_loaded=True, expected_sha256=""):
    """Compile/register one trusted CHIRP-style driver from supplied source.

    PocketCHIRP owns download, approval, storage, backup and filesystem policy.
    The GPL engine receives only source text plus neutral filename/hash metadata.
    It never receives or stores a proprietary-app private filesystem path.
    """
    global _selected_radio_key, _selected_radio_class

    from chirp import directory

    previous_key = _selected_radio_key
    previous_identity = None
    try:
        if previous_key and previous_key in (_radio_catalog_by_key or {}):
            prev = _radio_catalog_by_key[previous_key]
            previous_identity = _custom_public_identity(prev)
    except Exception:
        previous_identity = None

    safe_filename = os.path.basename(str(filename or "custom_driver.py").strip())
    if not safe_filename.lower().endswith(".py"):
        safe_filename += ".py"
    if safe_filename in ("", ".py"):
        safe_filename = "custom_driver.py"

    if isinstance(source_text, bytes):
        source_bytes = bytes(source_text)
    else:
        source_bytes = str(source_text or "").encode("utf-8")
    if not source_bytes:
        raise ValueError("Custom driver source is empty")

    digest = hashlib.sha256(source_bytes).hexdigest()
    expected = str(expected_sha256 or "").strip().lower()
    if expected and digest.lower() != expected:
        raise ValueError("Custom driver SHA-256 does not match PocketCHIRP metadata")

    module_name = "chirp.drivers.pocketchirp_custom_" + digest[:16]
    synthetic_path = "pocketchirp-custom://" + safe_filename

    existing = [
        e for e in _custom_driver_entries.values()
        if e.get("sha256") == digest
    ]
    if existing:
        for entry in existing:
            entry["driverFile"] = safe_filename
        _refresh_catalog_with_custom_entries()
        chosen = _choose_custom_driver_entry(
            existing,
            select_loaded=select_loaded,
            previous_key=previous_key,
            previous_identity=previous_identity,
        )
        if chosen is not None and bool(select_loaded):
            _selected_radio_key = chosen["key"]
            _selected_radio_class = _custom_radio_classes[chosen["key"]]
        return _json.dumps({
            "filename": safe_filename,
            "sha256": digest,
            "radios": existing,
            "registeredRadioCount": len(existing),
            "variantPolicy": "unlimited-independent-entries",
            "selectionPolicy": "preserve-exact-or-single-only",
            "cloneLifecyclePolicy": "vendor-agnostic-structural-mro",
            "selectedKey": chosen["key"] if (chosen is not None and bool(select_loaded)) else None,
            "alreadyLoaded": True,
            "runtimeCompat": {
                "gettextUnderscore": bool(hasattr(_builtins, "_")),
                "serialLog": bool(hasattr(AndroidSerialPipe, "log")),
            },
        })

    registry_before = dict(directory.DRV_TO_RADIO)
    reverse_registry_before = dict(getattr(directory, "RADIO_TO_DRV", {}))
    allow_dups_before = bool(getattr(directory, "ALLOW_DUPS", False))
    module_obj = _types.ModuleType(module_name)
    module_obj.__file__ = synthetic_path
    module_obj.__package__ = "chirp.drivers"
    module_obj.__loader__ = None
    module_obj.__dict__.setdefault("_", _builtins._)
    _sys.modules[module_name] = module_obj

    try:
        enable_rereg = getattr(directory, "enable_reregistrations", None)
        if callable(enable_rereg):
            enable_rereg()
        elif hasattr(directory, "ALLOW_DUPS"):
            directory.ALLOW_DUPS = True

        code = _compile_custom_driver_source(source_bytes, synthetic_path)
        exec(code, module_obj.__dict__)
        classes = _custom_driver_classes_from_module(module_obj, directory)
        if not classes:
            raise ValueError(
                "The Python source loaded, but it did not define a CHIRP radio driver "
                "with VENDOR and MODEL."
            )
    except Exception:
        directory.DRV_TO_RADIO.clear()
        directory.DRV_TO_RADIO.update(registry_before)
        if hasattr(directory, "RADIO_TO_DRV"):
            directory.RADIO_TO_DRV.clear()
            directory.RADIO_TO_DRV.update(reverse_registry_before)
        _sys.modules.pop(module_name, None)
        raise
    finally:
        directory.DRV_TO_RADIO.clear()
        directory.DRV_TO_RADIO.update(registry_before)
        if hasattr(directory, "RADIO_TO_DRV"):
            directory.RADIO_TO_DRV.clear()
            directory.RADIO_TO_DRV.update(reverse_registry_before)
        if hasattr(directory, "ALLOW_DUPS"):
            directory.ALLOW_DUPS = allow_dups_before

    # Replacing a saved filename replaces its visible runtime entries without
    # giving the engine any knowledge of PocketCHIRP's private directory.
    stale_keys = [
        key for key, entry in _custom_driver_entries.items()
        if str(entry.get("driverFile") or "") == safe_filename
    ]
    for key in stale_keys:
        _custom_driver_entries.pop(key, None)
        _custom_radio_classes.pop(key, None)

    entries = []
    for cls in classes:
        vendor = str(getattr(cls, "VENDOR", "") or "").strip()
        model = str(getattr(cls, "MODEL", "") or "").strip()
        variant = str(getattr(cls, "VARIANT", "") or "").strip()
        if not vendor or not model:
            continue

        key = f"custom:{digest[:16]}:{cls.__name__}"
        entry = {
            "key": key,
            "vendor": vendor,
            "model": model,
            "variant": variant,
            "module": module_name,
            "class": cls.__name__,
            "publicIdentity": {
                "vendor": vendor,
                "model": model,
                "variant": variant,
            },
            "kind": "custom",
            "customDriver": True,
            "driverFile": safe_filename,
            "sha256": digest,
        }
        _custom_radio_classes[key] = cls
        _custom_driver_entries[key] = entry
        entries.append(entry)

    if not entries:
        raise ValueError("No usable VENDOR/MODEL radio classes were found in the custom driver")

    _custom_driver_modules[digest] = module_obj
    _refresh_catalog_with_custom_entries()

    chosen = _choose_custom_driver_entry(
        entries,
        select_loaded=select_loaded,
        previous_key=previous_key,
        previous_identity=previous_identity,
    )
    if chosen is not None:
        _selected_radio_key = chosen["key"]
        _selected_radio_class = _custom_radio_classes[chosen["key"]]

    return _json.dumps({
        "filename": safe_filename,
        "sha256": digest,
        "radios": entries,
        "registeredRadioCount": len(entries),
        "variantPolicy": "unlimited-independent-entries",
        "selectionPolicy": "preserve-exact-or-single-only",
        "cloneLifecyclePolicy": "vendor-agnostic-structural-mro",
        "selectedKey": chosen["key"] if chosen is not None else None,
        "alreadyLoaded": False,
        "runtimeCompat": {
            "gettextUnderscore": bool(hasattr(_builtins, "_")),
            "serialLog": bool(hasattr(AndroidSerialPipe, "log")),
        },
    })



def unregister_custom_driver_runtime_json(filename, sha256=""):
    """Forget CHIRP runtime registrations only; PocketCHIRP owns files/inventory."""
    global _selected_radio_key, _selected_radio_class
    name = os.path.basename(str(filename or "").strip())
    digest_filter = str(sha256 or "").strip().lower()
    stale = []
    removed_radios = []
    for key, entry in list(_custom_driver_entries.items()):
        same_name = str(entry.get("driverFile") or "") == name
        same_digest = (not digest_filter or
                       str(entry.get("sha256") or "").lower() == digest_filter)
        if same_name and same_digest:
            stale.append(key)
            removed_radios.append({
                "key": str(entry.get("key") or ""),
                "vendor": str(entry.get("vendor") or ""),
                "model": str(entry.get("model") or ""),
                "variant": str(entry.get("variant") or ""),
            })
    removed_selected = bool(_selected_radio_key and _selected_radio_key in stale)
    digests = set()
    for key in stale:
        entry = _custom_driver_entries.pop(key, None)
        if entry and entry.get("sha256"):
            digests.add(str(entry.get("sha256")))
        _custom_radio_classes.pop(key, None)
    if removed_selected:
        _selected_radio_key = None
        _selected_radio_class = None
    for digest in digests:
        if not any(str(e.get("sha256") or "") == digest for e in _custom_driver_entries.values()):
            module = _custom_driver_modules.pop(digest, None)
            if module is not None:
                _sys.modules.pop(getattr(module, "__name__", ""), None)
    _refresh_catalog_with_custom_entries()
    return _json.dumps({
        "removedEntries": len(stale),
        "removedSelected": removed_selected,
        "removedRadios": removed_radios,
        "driverFile": name,
        "sha256": digest_filter,
    }, separators=(",", ":"))







def _entry(key=None):
    _ensure_radio_catalog()
    target = key or _selected_radio_key
    if target is None:
        raise ValueError("Choose a radio first.")
    if target not in _radio_catalog_by_key:
        raise ValueError("Unknown bundled radio selection")
    return _radio_catalog_by_key[target]



def _find_loaded_radio_class(entry):
    """Resolve a bundled CHIRP class or trusted CHIRP-compatible custom driver."""
    from chirp import directory

    if entry.get("customDriver") or entry.get("kind") == "custom":
        cls = _custom_radio_classes.get(entry.get("key"))
        if isinstance(cls, type):
            return cls
        raise ValueError(
            f"Custom driver is not loaded for {entry.get('vendor', '')} "
            f"{entry.get('model', '')}. Reload the Python driver."
        )

    module_name = entry.get("module") or ""
    if not module_name:
        raise ValueError(
            f"No executable CHIRP driver mapping for "
            f"{entry['vendor']} {entry['model']}"
        )

    module_obj = _importlib.import_module("chirp.drivers." + module_name)

    # Canonical driver.
    if entry.get("kind") == "driver":
        cls = getattr(module_obj, entry.get("class", ""), None)
        if isinstance(cls, type):
            return cls

    # Python ALIASES are resolved exactly as desktop CHIRP does.
    for cls in list(directory.DRV_TO_RADIO.values()):
        if cls.__module__ != module_obj.__name__:
            continue
        for alias in (getattr(cls, "ALIASES", []) or []):
            if (getattr(alias, "VENDOR", None) == entry["vendor"] and
                    getattr(alias, "MODEL", None) == entry["model"] and
                    (getattr(alias, "VARIANT", "") or "") ==
                    (entry.get("variant", "") or "")):
                class DynamicRadioAlias(cls):
                    _orig_rclass = cls
                    VENDOR = entry["vendor"]
                    MODEL = entry["model"]
                    VARIANT = entry.get("variant", "") or ""
                return DynamicRadioAlias

    # model_alias_map.yaml entries intentionally are NOT Python aliases.
    # The development-PC catalog export has already flattened each one to
    # CHIRP's executable driver module/class. Use that class while preserving the marketed
    # vendor/model in the UI and saved-image metadata.
    # Map aliases can target another CHIRP alias. In that case class is the
    # label-only Alias type while parentClass is the registered Radio backend.
    # Prefer parentClass for map aliases, and never construct an executable
    # DynamicMappedAlias from a non-Radio label class.
    from chirp import chirp_common as _chirp_common
    if entry.get("kind") == "map-alias":
        executable_class = entry.get("parentClass") or entry.get("class") or ""
    else:
        executable_class = entry.get("class") or entry.get("parentClass") or ""
    cls = getattr(module_obj, executable_class, None)

    if (not isinstance(cls, type) or
            not issubclass(cls, _chirp_common.Radio)) and entry.get("parentClass"):
        cls = getattr(module_obj, entry["parentClass"], None)

    if isinstance(cls, type) and issubclass(cls, _chirp_common.Radio):
        class DynamicMappedAlias(cls):
            _orig_rclass = cls
            VENDOR = entry["vendor"]
            MODEL = entry["model"]
            VARIANT = entry.get("variant", "") or ""
        return DynamicMappedAlias

    raise ValueError(
        f"Could not resolve bundled CHIRP driver for "
        f"{entry['vendor']} {entry['model']} "
        f"({module_name}.{executable_class})"
    )


def select_radio(key):
    global _selected_radio_key, _selected_radio_class
    e = _entry(str(key))
    _selected_radio_class = _find_loaded_radio_class(e)
    _selected_radio_key = e["key"]
    return _json.dumps({
        "key": e["key"],
        "vendor": e["vendor"],
        "model": e["model"],
        "variant": e.get("variant", "") or "",
        "module": e["module"],
        "class": getattr(_selected_radio_class, "__name__", ""),
        "baud": int(getattr(_selected_radio_class, "BAUD_RATE", 9600) or 9600),
        "selectionPolicy": "exact-vendor-model-variant",
    })


def _selected_class():
    global _selected_radio_class
    if _selected_radio_class is None:
        _selected_radio_class = _find_loaded_radio_class(_entry())
    return _selected_radio_class


def _radio_identity(cls_or_radio):
    """Stable public identity used across every vendor."""
    return _custom_public_identity(cls_or_radio)


def _selected_public_identity_tuple():
    """Exact selected public identity; independent of how many sibling variants exist."""
    e = _entry()
    return (
        str(e.get("vendor", "") or "").strip(),
        str(e.get("model", "") or "").strip(),
        str(e.get("variant", "") or "").strip(),
    )


def _describe_public_identity_tuple(identity):
    vendor, model, variant = identity
    text = ("%s %s" % (vendor, model)).strip()
    return text + ((" [%s]" % variant) if variant else "")


def _note_exact_selected_driver(pipe, cls):
    selected = _selected_public_identity_tuple()
    actual = _radio_identity(cls)

    _transport_note(
        pipe,
        "Driver selection locked: %s -> %s.%s" % (
            _describe_public_identity_tuple(selected),
            getattr(cls, "__module__", "?"),
            getattr(cls, "__name__", "?"),
        )
    )

    # Exact public identity remains preferred, but marketed aliases and sibling
    # labels may intentionally execute the exact same CHIRP implementation.
    # Do not reject those solely because VENDOR/MODEL text differs.  Equivalence
    # is deliberately narrow: after unwrapping PocketCHIRP's dynamic alias class,
    # the runtime implementation must be the exact same Python class object.
    if actual != selected:
        try:
            selected_impl = _unwrap_runtime_class(_selected_class())
            actual_impl = _unwrap_runtime_class(cls)
        except Exception:
            selected_impl = None
            actual_impl = None
        if selected_impl is actual_impl and selected_impl is not None:
            _transport_note(
                pipe,
                "Compatible marketed identity accepted: %s uses the same backend %s.%s" % (
                    _describe_public_identity_tuple(actual),
                    getattr(selected_impl, "__module__", "?"),
                    getattr(selected_impl, "__name__", "?"),
                )
            )
            return
        raise ValueError(
            "Selected radio identity mismatch: catalog=%s class=%s and backend classes differ. "
            "PocketCHIRP will not silently substitute an unrelated driver." % (
                _describe_public_identity_tuple(selected),
                _describe_public_identity_tuple(actual),
            )
        )


def _status_callback(radio, java_transport):
    """Bridge CHIRP status without putting UI IPC in BLE protocol hot loops."""
    pipe = getattr(radio, "pipe", None)

    # Native/direct BLE benefits from keeping synchronous Python->Java UI work
    # out of the protocol hot loop. Ordinary serial transports retain the driver's
    # normal callback cadence; PocketCHIRP applies its own app-side UI throttling.
    throttle = bool(getattr(pipe, "is_ble", False))
    last_sent_cur = None
    last_sent_max = None
    last_sent_msg = None

    def cb(status):
        nonlocal last_sent_cur, last_sent_max, last_sent_msg
        try:
            message = str(status.msg)
            current = int(status.cur)
            maximum = int(status.max)

            if throttle:
                # Always forward starts, completion, message/range changes and
                # resets. Ordinary clone-loop progress is coalesced to every
                # eight units. This was fluid on the UV-5R Mini while removing
                # hundreds of synchronous Python->Java callbacks.
                send = (
                    last_sent_cur is None
                    or current <= 0
                    or (maximum > 0 and current >= maximum)
                    or message != last_sent_msg
                    or maximum != last_sent_max
                    or current < last_sent_cur
                    or (current - last_sent_cur) >= 8
                )
                if not send:
                    return

            java_transport.onChirpProgress(message, current, maximum)
            last_sent_cur = current
            last_sent_max = maximum
            last_sent_msg = message
        except Exception:
            pass

    radio.status_fn = cb


def _store_downloaded_radio(radio):
    global _last_image_bytes, _last_raw_bytes, _last_hash_info
    name = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tmp:
            name = tmp.name
        _stamp_custom_image_metadata(radio)
        radio.save(name)
        with open(name, "rb") as f:
            _last_image_bytes = f.read()
    finally:
        if name:
            try:
                os.unlink(name)
            except OSError:
                pass

    _last_raw_bytes, _ = _split_chirp_img(_last_image_bytes)
    raw_sha = hashlib.sha256(_last_raw_bytes).hexdigest()
    img_sha = hashlib.sha256(_last_image_bytes).hexdigest()
    _last_hash_info = (
        f"Raw payload bytes: {len(_last_raw_bytes)}\n"
        f"Raw payload SHA-256: {raw_sha}\n"
        f"CHIRP .img bytes: {len(_last_image_bytes)}\n"
        f"Full .img SHA-256: {img_sha}"
    )
def selected_driver_identification_payloads_json():
    """Return optional conservative identification payloads for Deep BLE Probe.

    Deep BLE Probe does not require a selected radio. If no radio is selected,
    return an empty payload set so Android can still enumerate FFxx services,
    characteristics, notification/indication endpoints, AE10, and other GATT
    transport metadata without transmitting a clone-protocol payload.

    If a radio is selected, return only that CHIRP driver's normal
    identification byte strings. This never calls sync_out() and never returns
    radio image blocks.
    """
    try:
        cls = _selected_class()
    except Exception:
        return __import__("json").dumps({
            "selected": False,
            "vendor": "",
            "model": "",
            "variant": "",
            "baud": 9600,
            "payloads": [],
        }, separators=(",", ":"))

    payloads = []
    seen = set()

    def add(value, label):
        if isinstance(value, str):
            value = value.encode("latin1", errors="ignore")
        if not isinstance(value, (bytes, bytearray)):
            return
        value = bytes(value)
        if not value or len(value) > 256 or value in seen:
            return
        seen.add(value)
        payloads.append({
            "label": str(label),
            "base64": base64.b64encode(value).decode("ascii"),
            "hex": value.hex(),
            "bytes": len(value),
        })

    idents = getattr(cls, "_idents", None)
    if isinstance(idents, (list, tuple)):
        for i, value in enumerate(idents[:8]):
            add(value, f"_idents[{i}]")

    for name in ("_magic", "MAGIC", "magic", "PROGRAM_CMD", "PROGRAM_COMMAND"):
        value = getattr(cls, name, None)
        if isinstance(value, (bytes, bytearray, str)):
            add(value, name)

    magics = getattr(cls, "_magics", None)
    if isinstance(magics, (list, tuple)):
        for i, item in enumerate(magics[:8]):
            value = item[0] if isinstance(item, (list, tuple)) and item else item
            if isinstance(value, (bytes, bytearray, str)):
                add(value, f"_magics[{i}]")

    return __import__("json").dumps({
        "selected": True,
        "vendor": str(getattr(cls, "VENDOR", "") or ""),
        "model": str(getattr(cls, "MODEL", "") or ""),
        "variant": str(getattr(cls, "VARIANT", "") or ""),
        "baud": int(getattr(cls, "BAUD_RATE", 9600) or 9600),
        "payloads": payloads[:8],
    }, separators=(",", ":"))




class _ProbeBudgetExceeded(Exception):
    pass


class _GuardedDetectPipe(AndroidSerialPipe):
    """AndroidSerialPipe with strict budgets for CHIRP detect_from_serial()."""

    def __init__(self, java_transport, max_write=512, max_read=1536,
                 max_ops=160, max_seconds=8.0):
        super().__init__(java_transport)
        self._probe_max_write = int(max_write)
        self._probe_max_read = int(max_read)
        self._probe_max_ops = int(max_ops)
        self._probe_deadline = time.monotonic() + float(max_seconds)
        self._probe_written = 0
        self._probe_read = 0
        self._probe_ops = 0
        self._probe_tx = []
        self._probe_rx = []
        self._probe_bauds = []
        self.timeout = 0.75
        self.write_timeout = 0.75

    def _check(self):
        self._probe_ops += 1
        if self._probe_ops > self._probe_max_ops:
            raise _ProbeBudgetExceeded("operation budget exceeded")
        if time.monotonic() > self._probe_deadline:
            raise _ProbeBudgetExceeded("time budget exceeded")

    @property
    def baudrate(self):
        return AndroidSerialPipe.baudrate.fget(self)

    @baudrate.setter
    def baudrate(self, value):
        self._check()
        value = int(value)
        AndroidSerialPipe.baudrate.fset(self, value)
        if not self._probe_bauds or self._probe_bauds[-1] != value:
            self._probe_bauds.append(value)

    @property
    def timeout(self):
        return AndroidSerialPipe.timeout.fget(self)

    @timeout.setter
    def timeout(self, value):
        value = 0.75 if value is None else min(0.75, max(0.02, float(value)))
        AndroidSerialPipe.timeout.fset(self, value)

    @property
    def write_timeout(self):
        return AndroidSerialPipe.write_timeout.fget(self)

    @write_timeout.setter
    def write_timeout(self, value):
        value = 0.75 if value is None else min(0.75, max(0.02, float(value)))
        AndroidSerialPipe.write_timeout.fset(self, value)

    def write(self, data):
        self._check()
        raw = bytes(data)
        if len(raw) > 128:
            raise _ProbeBudgetExceeded(
                "single write too large for identification probe (%d bytes)" %
                len(raw))
        if self._probe_written + len(raw) > self._probe_max_write:
            raise _ProbeBudgetExceeded("write byte budget exceeded")
        count = super().write(raw)
        self._probe_written += max(0, int(count))
        self._probe_tx.append({
            "baud": int(self.baudrate),
            "hex": raw.hex(),
            "bytes": len(raw),
        })
        return count

    def read(self, size=1):
        self._check()
        size = max(0, int(size))
        if size <= 0:
            return b""
        remaining = self._probe_max_read - self._probe_read
        if remaining <= 0:
            raise _ProbeBudgetExceeded("read byte budget exceeded")
        ask = min(size, remaining, 256)
        data = super().read(ask)
        self._probe_read += len(data)
        if data:
            self._probe_rx.append({
                "baud": int(self.baudrate),
                "hex": bytes(data).hex(),
                "bytes": len(data),
                "ascii": "".join(
                    chr(b) if 32 <= b < 127 else "."
                    for b in bytes(data)[:128]),
            })
        return data

    def reset_input_buffer(self):
        self._check()
        return super().reset_input_buffer()

    flushInput = reset_input_buffer

    def transcript(self):
        return {
            "writtenBytes": self._probe_written,
            "readBytes": self._probe_read,
            "operations": self._probe_ops,
            "bauds": list(self._probe_bauds),
            "tx": list(self._probe_tx),
            "rx": list(self._probe_rx),
        }


def _native_detector_owner(cls):
    try:
        for base in cls.__mro__:
            if "detect_from_serial" in getattr(base, "__dict__", {}):
                return base
    except Exception:
        pass
    return None


def _native_detector_roots():
    roots = {}
    if _radio_catalog_cache is None:
        return []

    for entry in (_radio_catalog_cache.get("radios") or []):
        try:
            cls = _find_loaded_radio_class(entry)
            owner = _native_detector_owner(cls)
            if owner is None:
                continue
            # Ignore CHIRP's abstract/base detection interface: only concrete
            # driver modules are active Radio Auto-Detect families.
            if not str(getattr(owner, "__module__", "")).startswith("chirp.drivers."):
                continue
            if owner.__dict__.get("detect_from_serial") is None:
                continue
            key = "%s.%s" % (owner.__module__, owner.__name__)
            roots[key] = owner
        except Exception:
            continue

    out = list(roots.items())
    priority_modules = {
        "chirp.drivers.uvk5": 0,
        "chirp.drivers.tdh8": 1,
        "chirp.drivers.ga510": 2,
        "chirp.drivers.anytone778uv": 3,
        "chirp.drivers.leixen": 4,
        "chirp.drivers.tdm11": 5,
        "chirp.drivers.h777": 6,
    }
    out.sort(key=lambda kv: (
        priority_modules.get(kv[1].__module__, 50),
        kv[0].lower(),
    ))
    return out



def _probe_reset(java_transport, baud, family):
    """Request a clean transport session before an independent family probe."""
    reset = getattr(java_transport, "resetProbeSession", None)
    if reset is None:
        # Older Java bridge: only purge as compatibility fallback.
        try:
            java_transport.clearInputBuffer()
            java_transport.clearOutputBuffer()
            java_transport.setSerialParameters(int(baud), 8, 1.0, "N")
            java_transport.clearInputBuffer()
        except Exception:
            pass
        return "legacy-logical-reset"
    return str(reset(int(baud), str(family)))


def _probe_reset_info(java_transport):
    try:
        return {
            "count": int(java_transport.getProbeResetCount()),
            "mode": str(java_transport.getProbeResetMode()),
            "hard": bool(java_transport.hasHardProbeReset()),
        }
    except Exception:
        return {"count": 0, "mode": "unknown", "hard": False}




def _native_transcript_has_independent_rx(transcript):
    """Return True only if native detector RX contains evidence beyond TX echo.

    This deliberately rejects the exact failure seen with echoing programming
    cables: the detector transmits a packet and receives only the identical
    packet back. A real detector match must contain at least one RX byte which
    cannot be completely explained by the ordered TX stream.
    """
    tx_chunks = []
    rx_chunks = []
    for row in transcript.get("tx", []) or []:
        try:
            tx_chunks.append(bytes.fromhex(str(row.get("hex", ""))))
        except Exception:
            pass
    for row in transcript.get("rx", []) or []:
        try:
            rx_chunks.append(bytes.fromhex(str(row.get("hex", ""))))
        except Exception:
            pass

    tx = b"".join(tx_chunks)
    rx = b"".join(rx_chunks)

    if not rx:
        return False, {
            "independentRx": False,
            "reason": "no-rx",
            "txBytes": len(tx),
            "rxBytes": 0,
        }

    # Exact whole-stream echo: no independent radio evidence whatsoever.
    if tx and rx == tx:
        return False, {
            "independentRx": False,
            "reason": "exact-whole-stream-tx-echo",
            "txBytes": len(tx),
            "rxBytes": len(rx),
            "echoBytes": len(rx),
        }

    # Ordered per-write echo. This handles drivers which read after each write
    # and therefore record several RX chunks rather than one concatenated RX.
    if tx_chunks and len(tx_chunks) == len(rx_chunks):
        if all(a == b for a, b in zip(tx_chunks, rx_chunks)):
            return False, {
                "independentRx": False,
                "reason": "exact-per-write-tx-echo",
                "txBytes": len(tx),
                "rxBytes": len(rx),
                "echoBytes": len(rx),
            }

    # Leading full-stream echo plus additional bytes is valid independent
    # evidence; only the bytes after the complete echo count.
    if tx and rx.startswith(tx) and len(rx) > len(tx):
        extra = rx[len(tx):]
        return True, {
            "independentRx": True,
            "reason": "rx-after-complete-leading-echo",
            "txBytes": len(tx),
            "rxBytes": len(rx),
            "echoBytes": len(tx),
            "independentRxBytes": len(extra),
            "independentRxHex": extra[:128].hex(),
        }

    return True, {
        "independentRx": True,
        "reason": "rx-not-explained-by-tx-echo",
        "txBytes": len(tx),
        "rxBytes": len(rx),
    }



def _native_detect_result(java_transport, include_modules=None, exclude_modules=None):
    """Run CHIRP serial detectors under strict identification-only budgets."""
    attempts = []

    include_modules = set(include_modules or [])
    exclude_modules = set(exclude_modules or [])
    for detector_key, owner in _native_detector_roots():
        owner_module = str(getattr(owner, "__module__", "")).split(".")[-1]
        if include_modules and owner_module not in include_modules:
            continue
        if owner_module in exclude_modules:
            continue
        start_baud = int(getattr(owner, "BAUD_RATE", 9600) or 9600)
        reset_mode = _probe_reset(java_transport, start_baud, detector_key)
        pipe = _GuardedDetectPipe(java_transport)
        try:
            pipe.reset_input_buffer()
            pipe.reset_output_buffer()
            pipe.baudrate = start_baud

            detector = getattr(owner, "detect_from_serial")
            started = time.monotonic()
            result_cls = detector(pipe)
            elapsed = int((time.monotonic() - started) * 1000)

            if result_cls is not None:
                transcript = pipe.transcript()
                independent_rx, evidence = (
                    _native_transcript_has_independent_rx(transcript))

                if not independent_rx:
                    attempts.append({
                        "detector": detector_key,
                        "startBaud": start_baud,
                        "elapsedMs": elapsed,
                        "status": "rejected-echo-only",
                        "resetMode": reset_mode,
                        "claimedVendor": str(
                            getattr(result_cls, "VENDOR", "") or ""),
                        "claimedModel": str(
                            getattr(result_cls, "MODEL", "") or ""),
                        "claimedVariant": str(
                            getattr(result_cls, "VARIANT", "") or ""),
                        "claimedClass": str(
                            getattr(result_cls, "__name__", "") or ""),
                        "evidenceValidation": evidence,
                        "transcript": transcript,
                    })
                    try:
                        pipe.reset_input_buffer()
                        pipe.reset_output_buffer()
                    except Exception:
                        pass
                    time.sleep(0.06)
                    continue

                attempt = {
                    "detector": detector_key,
                    "startBaud": start_baud,
                    "elapsedMs": elapsed,
                    "status": "matched",
                    "resetMode": reset_mode,
                    "vendor": str(getattr(result_cls, "VENDOR", "") or ""),
                    "model": str(getattr(result_cls, "MODEL", "") or ""),
                    "variant": str(getattr(result_cls, "VARIANT", "") or ""),
                    "module": str(getattr(result_cls, "__module__", "") or ""),
                    "class": str(getattr(result_cls, "__name__", "") or ""),
                    "evidenceValidation": evidence,
                    "transcript": transcript,
                }
                printable = []
                for rx in attempt["transcript"].get("rx", []):
                    text = rx.get("ascii", "").strip(".")
                    if len(text) >= 3 and text not in printable:
                        printable.append(text)
                if printable:
                    attempt["printableResponses"] = printable[:12]

                attempts.append(attempt)
                return {
                    "matched": True,
                    "confidence": "high",
                    "suggested": {
                        "vendor": attempt["vendor"],
                        "model": attempt["model"],
                        "variant": attempt["variant"],
                        "module": attempt["module"],
                        "class": attempt["class"],
                        "detector": detector_key,
                    },
                    "attempts": attempts,
                }

        except _ProbeBudgetExceeded as e:
            attempts.append({
                "detector": detector_key,
                "status": "budget-stop",
                "resetMode": reset_mode,
                "error": str(e),
                "transcript": pipe.transcript(),
            })
        except Exception as e:
            attempts.append({
                "detector": detector_key,
                "status": "no-match",
                "resetMode": reset_mode,
                "error": "%s: %s" % (e.__class__.__name__, e),
                "transcript": pipe.transcript(),
            })

        try:
            pipe.reset_input_buffer()
            pipe.reset_output_buffer()
        except Exception:
            pass
        time.sleep(0.06)

    return {
        "matched": False,
        "confidence": "none",
        "suggested": None,
        "attempts": attempts,
    }



def _auto_probe_payloads_for_class(cls):
    """Conservative static CHIRP identification/program-entry tokens only."""
    rows = []
    seen = set()

    def add(value, label):
        if isinstance(value, str):
            value = value.encode("latin1", errors="ignore")
        if not isinstance(value, (bytes, bytearray)):
            return
        value = bytes(value)
        if not value or len(value) > 64 or value in seen:
            return
        seen.add(value)
        rows.append((str(label), value))

    idents = getattr(cls, "_idents", None)
    if isinstance(idents, (list, tuple)):
        for i, value in enumerate(idents[:12]):
            add(value, f"_idents[{i}]")

    for name in (
        "_magic", "_magic0", "_MAGIC", "MAGIC", "magic",
        "PROGRAM_CMD", "PROGRAM_COMMAND",
        "_program_cmd", "_program_command",
        "IDENT", "IDENT_CMD", "ID_CMD",
    ):
        value = getattr(cls, name, None)
        if isinstance(value, (bytes, bytearray, str)):
            add(value, name)

    magics = getattr(cls, "_magics", None)
    if isinstance(magics, (list, tuple)):
        for i, item in enumerate(magics[:12]):
            value = item[0] if isinstance(item, (list, tuple)) and item else item
            add(value, f"_magics[{i}]")

    return rows





# Expected first responses audited from the bundled CHIRP driver sources.
# These are family-entry/identification exchanges only, not clone data.
_FAST_FAMILY_RULES = {
    # Baofeng-derived clone families.
    "uv5r": {"kind": "exact", "value": "06", "label": "Baofeng UV-5R/UV-82 family"},
    "baofeng_common": {"kind": "exact", "value": "06", "label": "Baofeng common clone family"},
    "hg_uv98": {"kind": "exact", "value": "06", "label": "HG-UV98 family"},
    "uvb5": {"kind": "exact", "value": "06", "label": "UV-B5 family"},
    "th350": {"kind": "exact", "value": "06", "label": "TYT TH-350 family"},
    "lt725uv": {"kind": "exact", "value": "06", "label": "LT-725UV family"},
    "tk8102": {"kind": "exact", "value": "06", "label": "Kenwood TK-x102 family"},
    "tk3140": {"kind": "exact", "value": "06", "label": "Kenwood TK-x140 family"},

    # Kenwood high-speed mode starts with 0x16 before changing baud.
    "tk8180": {"kind": "exact", "value": "16", "label": "Kenwood TK-x180 family"},

    # TYT mobiles acknowledge initial programming command with ASCII A.
    "th9800": {"kind": "exact", "value": "41", "label": "TYT TH-9800 family"},
    "th7800": {"kind": "exact", "value": "41", "label": "TYT TH-7800 family"},

    # Several Retevis-style radios answer 06 30.
    "rh5r_v2": {"kind": "exact", "value": "0630", "label": "RH5R-v2 family"},
    "retevis_rt87": {"kind": "exact", "value": "0630", "label": "Retevis RT87 family"},

    # Alinco ASCII command-mode radios return OK.
    "alinco": {"kind": "ascii_contains", "value": "OK", "label": "Alinco command-mode family"},

    # TH-UV88 family returns a 36-byte framed fingerprint ending FD.
    "th_uv88": {"kind": "prefix_suffix", "prefix": "fefeefeee1", "suffix": "fd",
                "label": "TYT/clone UV88 family"},

    # BTECH/QYT mobile family returns a 50-byte ID block whose first byte is ACK.
    "btech": {"kind": "prefix", "value": "06", "minBytes": 20,
              "label": "BTECH/QYT mobile family"},
}


def _fast_family_expected(module_name, response):
    short = str(module_name or "").split(".")[-1]
    rule = _FAST_FAMILY_RULES.get(short)
    if not rule or not response:
        return False, None

    kind = rule.get("kind")
    if kind == "exact":
        ok = response == bytes.fromhex(rule["value"])
    elif kind == "prefix":
        value = bytes.fromhex(rule["value"])
        ok = response.startswith(value) and len(response) >= int(rule.get("minBytes", 1))
    elif kind == "ascii_contains":
        ok = rule["value"].encode("ascii") in response
    elif kind == "prefix_suffix":
        ok = (response.startswith(bytes.fromhex(rule["prefix"]))
              and response.endswith(bytes.fromhex(rule["suffix"])))
    else:
        ok = False
    return ok, rule


def _derived_fast_family_tokens(cls):
    """Extra first-stage tokens which CHIRP constructs in code instead of attrs."""
    module = str(getattr(cls, "__module__", "")).split(".")[-1]
    rows = []

    def add(value, label):
        if isinstance(value, str):
            value = value.encode("latin1", errors="ignore")
        if isinstance(value, (bytes, bytearray)) and 0 < len(value) <= 64:
            rows.append((bytes(value), label))

    if module == "alinco":
        model = getattr(cls, "_model", None)
        if isinstance(model, (bytes, bytearray)) and model and model != b"NONE":
            add(bytes(model) + b"\r\n", "_model+CRLF")
    elif module == "alinco_dr735t":
        add(b"AL~WHO\r\n", "AL~WHO")
    elif module == "th9800":
        add(b"\x02PROGRA", "program-entry")
    elif module == "th7800":
        add(b"\x02SPECPR", "program-entry")
    elif module == "rh5r_v2":
        add(b"PGM2015", "program-entry")
    elif module in ("tk8102", "tk3140", "tk8180"):
        add(b"PROGRAM", "program-entry")
    elif module == "uvb5":
        add(b"\x05PROGRAM", "program-entry")
    elif module == "th350":
        add(b"\x05TROGRAM", "program-entry")
    elif module == "hg_uv98":
        add(b"NiNHSG0N", "program-entry")
    elif module == "lt725uv":
        add(b"PROM_LIN", "program-entry")
    elif module == "vgc":
        add(b"V66LINK", "program-entry")

    # Wouxun's original driver stores actual query frames in _querymodels.
    if module == "wouxun":
        values = getattr(cls, "_querymodels", None)
        if isinstance(values, (list, tuple)):
            for i, value in enumerate(values[:4]):
                add(value, "_querymodels[%d]" % i)

    return rows


def _fast_family_catalog():
    """One short gateway probe per unique family token, sourced from CHIRP classes."""
    if _radio_catalog_cache is None:
        return []

    grouped = {}
    for entry in (_radio_catalog_cache.get("radios") or []):
        try:
            cls = _find_loaded_radio_class(entry)
            module = str(getattr(cls, "__module__", "")).split(".")[-1]
            baud = int(getattr(cls, "BAUD_RATE", 9600) or 9600)

            tokens = []
            for label, payload in _auto_probe_payloads_for_class(cls):
                # Static helper returns (label,payload).
                tokens.append((payload, label))
            tokens.extend(_derived_fast_family_tokens(cls))

            for payload, label in tokens:
                if not isinstance(payload, (bytes, bytearray)):
                    continue
                payload = bytes(payload)
                # Only source-audited families get the ultra-fast strong matcher.
                if module not in _FAST_FAMILY_RULES:
                    continue
                key = (module, baud, payload)
                row = grouped.setdefault(key, {
                    "module": module,
                    "baud": baud,
                    "payloadHex": payload.hex(),
                    "label": label,
                    "drivers": [],
                })
                row["drivers"].append({
                    "key": entry.get("key", ""),
                    "vendor": entry.get("vendor", ""),
                    "model": entry.get("model", ""),
                    "variant": entry.get("variant", "") or "",
                    "module": entry.get("module", "") or module,
                    "class": entry.get("class", "") or entry.get("parentClass", "") or "",
                })
        except Exception:
            continue

    rows = list(grouped.values())

    # Family-shared probes are better gateways than one-off model probes.
    rows.sort(key=lambda r: (
        -len(r["drivers"]),
        0 if r["module"] in ("uv5r", "baofeng_common", "btech") else 1,
        r["baud"],
        len(bytes.fromhex(r["payloadHex"])),
    ))
    return rows


def _fast_family_probe_result(java_transport):
    """Quick source-derived family gate before the slower static catalog sweep."""
    import time as _time

    rows = _fast_family_catalog()
    attempts = []

    # Proven UV-82/UV5R-family handshake first among static-safe gateways.
    priority = {
        ("uv5r", "50bbff20130105"): 0,
    }
    rows.sort(key=lambda r: (
        priority.get((r.get("module"), r.get("payloadHex")), 50),
        -len(r.get("drivers") or []),
        r.get("module", ""),
        r.get("baud", 9600),
    ))

    try:
        _set_transport_timeout_ms(java_transport, 180)
        java_transport.setWriteTimeoutMs(400)
    except Exception:
        pass

    # Hard cap keeps this phase short even as the CHIRP catalog grows.
    for index, row in enumerate(rows[:48]):
        baud = int(row["baud"])
        payload = bytes.fromhex(row["payloadHex"])
        reset_mode = "reset-not-started"
        try:
            reset_mode = _probe_reset(
                java_transport, baud,
                "%s:%s" % (row.get("module", "family"), row.get("payloadLabel", row.get("label", "probe")))
            )
            _time.sleep(0.025)
            java_transport.writeBytes(payload)
            started = _time.monotonic()
            deadline = started + 0.20
            chunks = []

            while _time.monotonic() < deadline and sum(len(x) for x in chunks) < 96:
                try:
                    available = int(java_transport.availableBytes())
                except Exception:
                    available = 0
                if available > 0:
                    data = bytes(java_transport.readBytes(min(available, 96)))
                    if data:
                        chunks.append(data)
                        deadline = min(started + 0.32, deadline + 0.06)
                else:
                    _time.sleep(0.012)

            raw_response = b"".join(chunks)
            echo_detected = bool(
                payload and raw_response.startswith(payload))
            if echo_detected:
                response = raw_response[len(payload):]
            else:
                response = raw_response
            matched, rule = _fast_family_expected(row["module"], response)
            attempt = {
                "index": index + 1,
                "module": row["module"],
                "baud": baud,
                "payloadHex": payload.hex(),
                "payloadLabel": row["label"],
                "resetMode": reset_mode,
                "elapsedMs": int((_time.monotonic() - started) * 1000),
                "responseHex": response.hex(),
                "responseBytes": len(response),
                "rawResponseHex": raw_response.hex(),
                "echoDetected": echo_detected,
                "echoOnly": bool(echo_detected and not response),
                "echoStrippedBytes": len(payload) if echo_detected else 0,
                "matchedExpected": bool(matched),
            }
            attempts.append(attempt)

            if matched:
                candidates = row["drivers"]
                label = rule.get("label", row["module"])
                suggested = None
                confidence = "family-high"
                if len(candidates) == 1:
                    suggested = dict(candidates[0])
                    confidence = "high"
                else:
                    # Family-level match: don't pretend an alias/model is exact.
                    suggested = {
                        "vendor": candidates[0].get("vendor", "") if
                                  len({d.get("vendor","") for d in candidates}) == 1 else "",
                        "model": label,
                        "variant": "",
                        "module": row["module"],
                        "class": "",
                        "familyCandidateCount": len(candidates),
                    }

                return {
                    "matched": True,
                    "confidence": confidence,
                    "family": label,
                    "suggested": suggested,
                    "candidates": candidates,
                    "attempts": attempts,
                    "match": attempt,
                }

        except Exception as e:
            attempts.append({
                "index": index + 1,
                "module": row["module"],
                "baud": baud,
                "payloadHex": payload.hex(),
                "payloadLabel": row["label"],
                "resetMode": reset_mode,
                "error": "%s: %s" % (e.__class__.__name__, e),
                "matchedExpected": False,
            })

    return {
        "matched": False,
        "confidence": "none",
        "family": None,
        "suggested": None,
        "candidates": [],
        "attempts": attempts,
    }




_SAFE_NATIVE_MODULES = {
    "uvk5", "tdh8", "ga510", "anytone778uv", "leixen", "tdm11", "h777",
}

_SAFE_VENDOR_MODULES = {
    "wouxun", "icf", "icw32", "ic208", "ic2100", "ic2200", "ic2300",
    "ic2720", "ic2820", "ict7h", "ict8", "ict70", "ict10", "icp7",
    "icq7", "icv80", "icv86", "icx8x", "icx90", "id31", "id51",
    "id51plus", "id800", "id880", "id5100", "icm710", "icf520",
    "radtel_t18", "radtel_rt490",
    "radioddity_gm30", "kguv8e",
    "anytone", "anytone_ht", "anytone_iii", "retevis_rt98", "th9000",
}

_SAFE_FAST_MODULES = set(_FAST_FAMILY_RULES.keys())



def _candidate_catalog_entries(candidates):
    by_key = {}
    if _radio_catalog_cache is not None:
        for entry in (_radio_catalog_cache.get("radios") or []):
            key = entry.get("key", "")
            if key:
                by_key[key] = entry
    out = []
    for c in candidates or []:
        entry = by_key.get(c.get("key", ""))
        if entry:
            try:
                out.append((c, entry, _find_loaded_radio_class(entry)))
            except Exception:
                pass
    return out


def _transport_read_exact(java_transport, count, timeout=0.75):
    import time as _time
    deadline = _time.monotonic() + float(timeout)
    data = bytearray()
    while len(data) < int(count) and _time.monotonic() < deadline:
        try:
            available = int(java_transport.availableBytes())
        except Exception:
            available = 0
        if available > 0:
            chunk = bytes(java_transport.readBytes(min(
                available, int(count) - len(data))))
            if chunk:
                data.extend(chunk)
                continue
        _time.sleep(0.008)
    return bytes(data)


def _transport_read_until(java_transport, stop_byte, maximum, timeout=0.75):
    import time as _time
    deadline = _time.monotonic() + float(timeout)
    data = bytearray()
    while len(data) < int(maximum) and _time.monotonic() < deadline:
        b = _transport_read_exact(java_transport, 1, 0.10)
        if not b:
            continue
        data.extend(b)
        if b[-1:] == bytes([int(stop_byte) & 0xFF]):
            break
    return bytes(data)


def _uv5r_read_block_safe(java_transport, address, size, first_command):
    import struct as _struct
    request = _struct.pack(">BHB", ord("S"), int(address), int(size))
    java_transport.writeBytes(request)
    if not first_command:
        ack = _transport_read_exact(java_transport, 1, 0.55)
        if ack != b"\x06":
            raise RuntimeError("UV5R metadata block was not acknowledged")

    # Match CHIRP uv5r.py _read_block(): exactly one four-byte response
    # header follows the optional ACK.
    header = _transport_read_exact(java_transport, 4, 0.55)
    if len(header) != 4:
        raise RuntimeError("UV5R metadata response header was short")
    cmd, addr, length = _struct.unpack(">BHB", header)
    if cmd != ord("X") or addr != int(address) or length != int(size):
        raise RuntimeError(
            "UV5R metadata header mismatch: got %s expected X/%04x/%02x"
            % (header.hex(), int(address), int(size)))
    payload = _transport_read_exact(java_transport, int(size), 0.80)
    if len(payload) != int(size):
        raise RuntimeError("UV5R metadata block was short")
    java_transport.writeBytes(b"\x06")
    return payload


def _safe_discriminate_uv5r(java_transport, fast):
    """UV5R/UV82 exact model discriminator using CHIRP's firmware metadata path.

    This performs only the normal identification exchange plus two read-only
    64-byte metadata blocks. It does not read channel/image memory ranges.
    """
    candidates = fast.get("candidates") or []
    match = fast.get("match") or {}
    magic = bytes.fromhex(match.get("payloadHex", ""))
    if not magic:
        return None

    reuse_live_session = (
        fast.get("sessionReusable")
        and fast.get("sessionStage") == "program-ack"
    )

    if reuse_live_session:
        # The family probe just received the valid 0x06 program ACK. Continue
        # the exact CHIRP sequence from that state. Do NOT reset/re-enter.
        reset_mode = str((fast.get("match") or {}).get(
            "resetMode", "live-program-ack-session"))
        entry_mode = "continued-from-family-program-ack"
    else:
        # Compatibility path for callers which did not hand us a live session.
        reset_mode = _probe_reset(
            java_transport, 9600, "uv5r:model-discriminator")
        java_transport.setSerialParameters(9600, 8, 1.0, "N")
        _set_transport_timeout_ms(java_transport, 500)
        java_transport.setWriteTimeoutMs(500)
        java_transport.clearInputBuffer()

        # CHIRP sends this magic byte-at-a-time with a short inter-byte delay.
        import time as _time
        for b in magic:
            java_transport.writeBytes(bytes([b]))
            _time.sleep(0.01)
        ack = _transport_read_exact(java_transport, 1, 0.75)
        if ack != b"\x06":
            raise RuntimeError(
                "UV5R discriminator did not receive program ACK")
        entry_mode = "fresh-reentry"

    _set_transport_timeout_ms(java_transport, 500)
    java_transport.setWriteTimeoutMs(500)
    java_transport.writeBytes(b"\x02")
    ident = _transport_read_until(java_transport, 0xDD, 12, 0.85)
    if len(ident) not in (8, 12):
        raise RuntimeError("UV5R discriminator ident length was %d" % len(ident))

    java_transport.writeBytes(b"\x06")
    ack2 = _transport_read_exact(java_transport, 1, 0.55)
    if ack2 != b"\x06":
        raise RuntimeError("UV5R discriminator second ACK failed")

    # CHIRP explicitly reads a non-aux block before the firmware block because
    # some radios otherwise return alternate aux data. Both are read-only.
    _uv5r_read_block_safe(java_transport, 0x1E80, 0x40, True)
    fwblock = _uv5r_read_block_safe(java_transport, 0x1EC0, 0x40, False)
    firmware = fwblock[48:62]

    exact = []
    candidate_details = []
    for c, entry, cls in _candidate_catalog_entries(candidates):
        basetypes = getattr(cls, "_basetype", None)
        tokens = []
        if isinstance(basetypes, (list, tuple)):
            tokens = [bytes(x) for x in basetypes
                      if isinstance(x, (bytes, bytearray))]
        hit = any(token and token in firmware for token in tokens)
        candidate_details.append({
            "vendor": c.get("vendor", ""),
            "model": c.get("model", ""),
            "class": c.get("class", ""),
            "baseTypes": [x.hex() for x in tokens],
            "matchedFirmware": bool(hit),
        })
        if hit:
            exact.append(dict(c))

    result = {
        "mode": "uv5r-readonly-firmware-basetype",
        "resetMode": reset_mode,
        "entryMode": entry_mode,
        "identHex": ident.hex(),
        "firmwareHex": firmware.hex(),
        "firmwareAscii": "".join(chr(b) if 32 <= b < 127 else "." for b in firmware),
        "metadataBytesRead": 128,
        "candidateDetails": candidate_details,
        "matches": exact,
    }
    if len(exact) == 1:
        result["suggested"] = exact[0]
        result["confidence"] = "high"
    elif exact:
        result["confidence"] = "family-high"
    else:
        result["confidence"] = "family-high"
    return result


def _safe_discriminate_from_existing_response(fast):
    """Narrow families whose initial safe response already contains fingerprints."""
    module = str((fast.get("match") or {}).get("module", ""))
    response_hex = (fast.get("match") or {}).get("responseHex", "")
    if not response_hex:
        return None
    response = bytes.fromhex(response_hex)
    candidates = fast.get("candidates") or []

    if module == "btech":
        exact = []
        details = []
        for c, entry, cls in _candidate_catalog_entries(candidates):
            fps = getattr(cls, "_fileid", None)
            fps = fps if isinstance(fps, (list, tuple)) else []
            vals = [bytes(x) for x in fps if isinstance(x, (bytes, bytearray))]
            hit = any(fp and fp in response for fp in vals)
            details.append({
                "vendor": c.get("vendor", ""),
                "model": c.get("model", ""),
                "fingerprints": [x.hex() for x in vals],
                "matched": bool(hit),
            })
            if hit:
                exact.append(dict(c))
        r = {
            "mode": "btech-existing-ident-fingerprint",
            "matches": exact,
            "candidateDetails": details,
            "extraTraffic": False,
        }
        if len(exact) == 1:
            r["suggested"] = exact[0]
            r["confidence"] = "high"
        elif exact:
            r["confidence"] = "family-high"
        return r

    if module == "th_uv88":
        exact = []
        details = []
        for c, entry, cls in _candidate_catalog_entries(candidates):
            fp = getattr(cls, "_fingerprint", None)
            fp = bytes(fp) if isinstance(fp, (bytes, bytearray)) else b""
            hit = bool(fp and response.startswith(fp) and response.endswith(b"\xFD"))
            details.append({
                "vendor": c.get("vendor", ""),
                "model": c.get("model", ""),
                "fingerprintHex": fp.hex(),
                "matched": bool(hit),
            })
            if hit:
                exact.append(dict(c))
        r = {
            "mode": "th-uv88-existing-response-fingerprint",
            "matches": exact,
            "candidateDetails": details,
            "extraTraffic": False,
        }
        if len(exact) == 1:
            r["suggested"] = exact[0]
            r["confidence"] = "high"
        elif exact:
            r["confidence"] = "family-high"
        return r

    return None


def _safe_discriminate_kenwood(java_transport, fast):
    module = str((fast.get("match") or {}).get("module", ""))
    candidates = fast.get("candidates") or []
    if module not in ("tk8102", "tk3140", "tk8180"):
        return None

    reset_mode = _probe_reset(java_transport, 9600, module + ":model-discriminator")
    _set_transport_timeout_ms(java_transport, 600)
    java_transport.setWriteTimeoutMs(500)

    if module == "tk8102":
        java_transport.setSerialParameters(9600, 8, 1.0, "E")
        java_transport.writeBytes(b"PROGRAM")
        if _transport_read_exact(java_transport, 1, 0.65) != b"\x06":
            raise RuntimeError("TK-x102 program ACK failed")
        java_transport.writeBytes(b"\x02")
        ident = _transport_read_exact(java_transport, 8, 0.75)
        java_transport.writeBytes(b"\x06")
        _transport_read_exact(java_transport, 1, 0.40)

        modelstr = ident[1:5].decode("ascii", errors="ignore")
        exact = [dict(c) for c in candidates
                 if str(c.get("model", "")).replace("TK-", "") == modelstr]

    elif module == "tk3140":
        java_transport.setSerialParameters(9600, 8, 2.0, "N")
        java_transport.writeBytes(b"PROGRAM")
        if _transport_read_exact(java_transport, 1, 0.65) != b"\x06":
            raise RuntimeError("TK-x140 program ACK failed")
        java_transport.writeBytes(b"\x02")
        ident = _transport_read_exact(java_transport, 8, 0.75)
        java_transport.writeBytes(b"\x06")
        if _transport_read_exact(java_transport, 1, 0.55) != b"\x06":
            raise RuntimeError("TK-x140 model ACK failed")
        exact = []
        for c, entry, cls in _candidate_catalog_entries(candidates):
            expected = getattr(cls, "_model", None)
            if isinstance(expected, (bytes, bytearray)) and ident == bytes(expected):
                exact.append(dict(c))

    else:
        java_transport.setSerialParameters(9600, 8, 2.0, "N")
        java_transport.writeBytes(b"PROGRAM")
        first = _transport_read_exact(java_transport, 1, 0.65)
        if first != b"\x16":
            raise RuntimeError("TK-x180 high-speed ACK failed")
        java_transport.setSerialParameters(19200, 8, 2.0, "N")
        if _transport_read_exact(java_transport, 1, 0.65) != b"\x06":
            raise RuntimeError("TK-x180 program ACK failed")
        java_transport.writeBytes(b"\x02")
        ident = _transport_read_exact(java_transport, 8, 0.75)
        java_transport.writeBytes(b"\x06")
        if _transport_read_exact(java_transport, 1, 0.55) != b"\x06":
            raise RuntimeError("TK-x180 model ACK failed")
        exact = []
        for c, entry, cls in _candidate_catalog_entries(candidates):
            expected = getattr(cls, "_model", None)
            if isinstance(expected, (bytes, bytearray)) and ident[:6] == bytes(expected):
                exact.append(dict(c))

    r = {
        "mode": module + "-readonly-ident",
        "resetMode": reset_mode,
        "identHex": ident.hex(),
        "identAscii": "".join(chr(b) if 32 <= b < 127 else "." for b in ident),
        "matches": exact,
    }
    if len(exact) == 1:
        r["suggested"] = exact[0]
        r["confidence"] = "high"
    elif exact:
        r["confidence"] = "family-high"
    else:
        r["confidence"] = "family-high"
    return r


def _safe_discriminate_rh5r(java_transport, fast):
    if str((fast.get("match") or {}).get("module", "")) != "rh5r_v2":
        return None
    import struct as _struct

    candidates = fast.get("candidates") or []
    reset_mode = _probe_reset(java_transport, 9600, "rh5r_v2:model-discriminator")
    java_transport.setSerialParameters(9600, 8, 1.0, "N")
    _set_transport_timeout_ms(java_transport, 700)
    java_transport.writeBytes(b"PGM2015")
    if _transport_read_exact(java_transport, 2, 0.70) != b"\x06\x30":
        raise RuntimeError("RH5R-v2 program ACK failed")

    # CHIRP's match_model discriminates this family from the eight bytes at
    # image offset 0x840. Read exactly the one 0x40-byte block containing it.
    java_transport.writeBytes(_struct.pack(">cHb", b"R", 0x840, 0x40))
    block = _transport_read_exact(java_transport, 0x44, 0.90)
    if len(block) != 0x44:
        raise RuntimeError("RH5R-v2 metadata block was short")
    data = block[4:]
    fileid = data[:8]

    exact = []
    for c, entry, cls in _candidate_catalog_entries(candidates):
        expected = getattr(cls, "_FILEID", None)
        if isinstance(expected, (bytes, bytearray)) and fileid == bytes(expected):
            exact.append(dict(c))

    r = {
        "mode": "rh5r-v2-readonly-fileid",
        "resetMode": reset_mode,
        "fileIdHex": fileid.hex(),
        "fileIdAscii": "".join(chr(b) if 32 <= b < 127 else "." for b in fileid),
        "metadataBytesRead": 64,
        "matches": exact,
    }
    if len(exact) == 1:
        r["suggested"] = exact[0]
        r["confidence"] = "high"
    elif exact:
        r["confidence"] = "family-high"
    else:
        r["confidence"] = "family-high"
    return r


def _safe_family_discriminator(java_transport, fast):
    """Try only source-audited non-destructive exact-model discriminators."""
    module = str((fast.get("match") or {}).get("module", ""))
    try:
        result = _safe_discriminate_from_existing_response(fast)
        if result:
            return result
        if module == "uv5r":
            return _safe_discriminate_uv5r(java_transport, fast)
        if module in ("tk8102", "tk3140", "tk8180"):
            return _safe_discriminate_kenwood(java_transport, fast)
        if module == "rh5r_v2":
            return _safe_discriminate_rh5r(java_transport, fast)
    except Exception as e:
        return {
            "mode": module + "-safe-discriminator",
            "error": "%s: %s" % (e.__class__.__name__, e),
            "matches": [],
            "confidence": "family-high",
        }
    return {
        "mode": "family-only-no-safe-exact-recipe",
        "matches": [],
        "confidence": fast.get("confidence", "family-high"),
        "reason": "CHIRP source does not provide a sufficiently small non-destructive exact-model discriminator for this family",
    }




def _safe_probe_uv5r_priority(java_transport):
    """One proven UV-82/UV5R family handshake before slower vendor probes."""
    payload = bytes.fromhex("50bbff20130105")
    try:
        reset_mode = _probe_reset(java_transport, 9600, "uv5r:priority-family")
        java_transport.setSerialParameters(9600, 8, 1.0, "N")
        _set_transport_timeout_ms(java_transport, 350)
        java_transport.setWriteTimeoutMs(350)
        java_transport.clearInputBuffer()
        java_transport.writeBytes(payload)
        response = _transport_read_exact(java_transport, 1, 0.40)
        if response == b"\x06":
            # Reuse the catalog's exact candidate grouping for this magic.
            rows = [
                r for r in _fast_family_catalog()
                if r.get("module") == "uv5r"
                and r.get("payloadHex") == payload.hex()
            ]
            if rows:
                row = rows[0]
                return {
                    "matched": True,
                    "confidence": "family-high",
                    "family": "Baofeng UV-5R/UV-82 family",
                    "suggested": {
                        "vendor": "",
                        "model": "Baofeng UV-5R/UV-82 family",
                        "variant": "",
                        "module": "uv5r",
                        "class": "",
                        "familyCandidateCount": len(row.get("drivers") or []),
                    },
                    "candidates": row.get("drivers") or [],
                    "match": {
                        "module": "uv5r",
                        "baud": 9600,
                        "payloadHex": payload.hex(),
                        "responseHex": response.hex(),
                        "responseBytes": len(response),
                        "matchedExpected": True,
                        "resetMode": reset_mode,
                    },
                    "attempts": [],
                    "sessionStage": "program-ack",
                    "sessionReusable": True,
                }
    except Exception:
        pass
    return {"matched": False}



def _probe_read_after_tx(java_transport, tx, expected_min=1,
                         timeout_s=0.70, max_bytes=128):
    """Collect a direct-probe reply and remove one confirmed cable echo.

    Echo removal is deliberately conservative:
      * only a complete leading byte-for-byte copy of TX is removed;
      * partial prefix matches are never discarded;
      * TX with no bytes after it is classified as echo-only/no response.
    """
    import time as _time

    tx = bytes(tx or b"")
    started = _time.monotonic()
    deadline = started + float(timeout_s)
    quiet_deadline = None
    chunks = []

    while _time.monotonic() < deadline:
        try:
            available = int(java_transport.availableBytes())
        except Exception:
            available = 0

        if available > 0:
            data = bytes(java_transport.readBytes(
                min(max(1, available), max_bytes)))
            if data:
                chunks.append(data)
                quiet_deadline = _time.monotonic() + 0.055
                if sum(len(x) for x in chunks) >= max_bytes:
                    break
        else:
            now = _time.monotonic()
            raw = b"".join(chunks)
            # Once enough non-echo reply bytes exist and the line has gone
            # quiet, return without unnecessarily waiting the full timeout.
            if quiet_deadline is not None and now >= quiet_deadline:
                if raw.startswith(tx) and len(raw) > len(tx):
                    if len(raw) - len(tx) >= int(expected_min):
                        break
                elif not tx or not raw.startswith(tx):
                    if len(raw) >= int(expected_min):
                        break
            _time.sleep(0.008)

    raw = b"".join(chunks)

    if tx and raw.startswith(tx):
        if len(raw) == len(tx):
            return b"", {
                "echoDetected": True,
                "echoOnly": True,
                "echoStrippedBytes": len(tx),
                "rawHex": raw.hex(),
            }
        return raw[len(tx):], {
            "echoDetected": True,
            "echoOnly": False,
            "echoStrippedBytes": len(tx),
            "rawHex": raw.hex(),
        }

    return raw, {
        "echoDetected": False,
        "echoOnly": False,
        "echoStrippedBytes": 0,
        "rawHex": raw.hex(),
    }


def _probe_write_read(java_transport, tx, expected_min=1,
                      timeout_s=0.70, max_bytes=128):
    tx = bytes(tx)
    java_transport.writeBytes(tx)
    return _probe_read_after_tx(
        java_transport, tx, expected_min, timeout_s, max_bytes)



def _safe_probe_wouxun(java_transport):
    """Original Wouxun query-model exchange: query token + 9-byte ID only."""
    probes = {}
    for entry in (_radio_catalog_cache.get("radios") or []) if _radio_catalog_cache else []:
        try:
            cls = _find_loaded_radio_class(entry)
            if str(getattr(cls, "__module__", "")).split(".")[-1] != "wouxun":
                continue
            model = getattr(cls, "_model", None)
            queries = getattr(cls, "_querymodels", None)
            if not isinstance(model, (bytes, bytearray)) or not isinstance(queries, (list, tuple)):
                continue
            model = bytes(model)
            for q in queries:
                if not isinstance(q, (bytes, bytearray)):
                    continue
                q = bytes(q)
                key = (int(getattr(cls, "BAUD_RATE", 9600) or 9600), q)
                probes.setdefault(key, []).append((entry, cls, model))
        except Exception:
            continue

    attempts = []
    for (baud, query), candidates in sorted(probes.items(), key=lambda x: (-len(x[1]), x[0][0], x[0][1])):
        try:
            reset_mode = _probe_reset(java_transport, baud, "wouxun:model-query")
            java_transport.setSerialParameters(baud, 8, 1.0, "N")
            _set_transport_timeout_ms(java_transport, 650)
            java_transport.setWriteTimeoutMs(450)
            java_transport.clearInputBuffer()
            resp, echo_info = _probe_write_read(
                java_transport, query, expected_min=9,
                timeout_s=0.80, max_bytes=32)
            attempt = {
                "vendorFamily": "Wouxun",
                "baud": baud,
                "queryHex": query.hex(),
                "responseHex": resp.hex(),
                "responseBytes": len(resp),
                "resetMode": reset_mode,
                "echoInfo": echo_info,
            }
            attempts.append(attempt)
            if len(resp) != 9:
                continue

            matches = []
            for entry, cls, expected in candidates:
                if resp[2:8] == expected:
                    matches.append({
                        "key": entry.get("key", ""),
                        "vendor": entry.get("vendor", ""),
                        "model": entry.get("model", ""),
                        "variant": entry.get("variant", "") or "",
                        "module": entry.get("module", "") or "wouxun",
                        "class": entry.get("class", "") or cls.__name__,
                    })
            if matches:
                suggested = matches[0] if len(matches) == 1 else {
                    "vendor": "Wouxun",
                    "model": "Wouxun family",
                    "variant": "",
                    "module": "wouxun",
                    "class": "",
                    "familyCandidateCount": len(matches),
                }
                return {
                    "matched": True,
                    "confidence": "high" if len(matches) == 1 else "family-high",
                    "family": "Wouxun",
                    "suggested": suggested,
                    "candidates": matches,
                    "attempts": attempts,
                    "identity": {
                        "responseHex": resp.hex(),
                        "modelIdHex": resp[2:8].hex(),
                        "modelIdAscii": "".join(chr(b) if 32 <= b < 127 else "." for b in resp[2:8]),
                    },
                }
        except Exception as e:
            attempts.append({
                "vendorFamily": "Wouxun",
                "baud": baud,
                "queryHex": query.hex(),
                "error": "%s: %s" % (e.__class__.__name__, e),
            })
    return {"matched": False, "attempts": attempts}



def _catalog_candidates_for_module(module_name):
    """Return catalog entry/class pairs for one bundled CHIRP driver module."""
    out = []
    for entry in (_radio_catalog_cache.get("radios") or []) if _radio_catalog_cache else []:
        try:
            cls = _find_loaded_radio_class(entry)
            module = str(getattr(cls, "__module__", "")).split(".")[-1]
            if module == str(module_name):
                out.append((entry, cls))
        except Exception:
            continue
    return out


def _candidate_dict(entry, cls, module_name):
    return {
        "key": entry.get("key", ""),
        "vendor": entry.get("vendor", ""),
        "model": entry.get("model", ""),
        "variant": entry.get("variant", "") or "",
        "module": entry.get("module", "") or str(module_name),
        "class": entry.get("class", "") or cls.__name__,
    }


def _safe_probe_radioddity_gm30(java_transport):
    """Radioddity GM-30/P13GMRS identity-only entry with explicit exit.

    CHIRP's radioddity_gm30 driver enters with PSEARCH at 57600 and expects
    exactly ACK + P13GMRS.  The driver exits programming with 06 06 00.
    This probe intentionally runs before ga510.detect_from_serial(), because
    that broader detector also tries this protocol and otherwise continues
    into unrelated handshakes after receiving the P13GMRS identity.
    """
    candidates = _catalog_candidates_for_module("radioddity_gm30")
    if not candidates:
        return {"matched": False, "attempts": []}

    grouped = {}
    for entry, cls in candidates:
        baud = int(getattr(cls, "BAUD_RATE", 57600) or 57600)
        grouped.setdefault(baud, []).append((entry, cls))

    attempts = []
    expected = b"\x06P13GMRS"
    for baud, rows in sorted(grouped.items()):
        reset_mode = "reset-not-started"
        resp = b""
        echo_info = {}
        exit_sent = False
        try:
            reset_mode = _probe_reset(
                java_transport, baud, "radioddity_gm30:p13gmrs-ident")
            java_transport.setSerialParameters(baud, 8, 1.0, "N")
            _set_transport_timeout_ms(java_transport, 650)
            java_transport.setWriteTimeoutMs(450)
            java_transport.clearInputBuffer()

            resp, echo_info = _probe_write_read(
                java_transport, b"PSEARCH", expected_min=8,
                timeout_s=0.80, max_bytes=24)

            # An ACK means PSEARCH entered the programming session.  Always
            # perform the driver's source-audited exit before returning or
            # moving on, even if the following identity bytes are unfamiliar.
            if resp[:1] == b"\x06":
                java_transport.writeBytes(b"\x06\x06\x00")
                exit_sent = True

            attempt = {
                "vendorFamily": "Radioddity GM-30/P13GMRS",
                "baud": baud,
                "queryHex": b"PSEARCH".hex(),
                "responseHex": resp.hex(),
                "responseBytes": len(resp),
                "resetMode": reset_mode,
                "echoInfo": echo_info,
                "exitSent": exit_sent,
            }
            attempts.append(attempt)

            if resp[:len(expected)] != expected:
                continue

            matches = [_candidate_dict(entry, cls, "radioddity_gm30")
                       for entry, cls in rows]
            suggested = matches[0] if len(matches) == 1 else {
                "vendor": "Radioddity",
                "model": "GM-30/P13GMRS compatible family",
                "variant": "",
                "module": "radioddity_gm30",
                "class": "",
                "familyCandidateCount": len(matches),
            }
            return {
                "matched": True,
                "confidence": "high" if len(matches) == 1 else "family-high",
                "family": "Radioddity GM-30/P13GMRS",
                "suggested": suggested,
                "candidates": matches,
                "attempts": attempts,
                "identity": {
                    "responseHex": resp[:len(expected)].hex(),
                    "identHex": resp[1:8].hex(),
                    "identAscii": "P13GMRS",
                },
            }
        except Exception as e:
            # If we saw an ACK but failed while exiting, make one best-effort
            # repeat of the driver's exit sequence.  Never send it to a radio
            # which did not acknowledge PSEARCH.
            if resp[:1] == b"\x06" and not exit_sent:
                try:
                    java_transport.writeBytes(b"\x06\x06\x00")
                    exit_sent = True
                except Exception:
                    pass
            attempts.append({
                "vendorFamily": "Radioddity GM-30/P13GMRS",
                "baud": baud,
                "queryHex": b"PSEARCH".hex(),
                "responseHex": resp.hex(),
                "resetMode": reset_mode,
                "echoInfo": echo_info,
                "exitSent": exit_sent,
                "error": "%s: %s" % (e.__class__.__name__, e),
            })

    return {"matched": False, "attempts": attempts}


def _safe_probe_kguv8e(java_transport):
    """Wouxun KG-UV8E framed/encrypted identity with explicit CMD_END.

    The KG-UV8E is not part of the older 9600-baud HiWOUXUN query protocol.
    Its CHIRP driver uses 19200 baud, CMD_ID (0x80), an encrypted/checksummed
    record, and CMD_END (0x81).  We reuse the driver's own record codec and
    only inspect the identity response; no memory-read command is issued.
    """
    candidates = _catalog_candidates_for_module("kguv8e")
    if not candidates:
        return {"matched": False, "attempts": []}

    attempts = []
    for entry, cls in candidates:
        baud = int(getattr(cls, "BAUD_RATE", 19200) or 19200)
        reset_mode = "reset-not-started"
        saw_record = False
        finish_sent = False
        responses = []
        last_resp = b""
        try:
            reset_mode = _probe_reset(
                java_transport, baud, "wouxun:kguv8e-ident")
            java_transport.setSerialParameters(baud, 8, 1.0, "N")
            _set_transport_timeout_ms(java_transport, 700)
            java_transport.setWriteTimeoutMs(450)
            java_transport.clearInputBuffer()

            pipe = LegacyAndroidSerialPipe(java_transport)
            pipe.baudrate = baud
            pipe.timeout = 0.85
            try:
                pipe.reset_input_buffer()
                pipe.reset_output_buffer()
            except Exception:
                pass

            radio = cls(pipe)
            expected = bytes(getattr(cls, "_model", b""))
            if not expected:
                raise RuntimeError("KG-UV8E driver has no _model identity")

            matched = False
            # CHIRP notes that the first KG-UV8E ID response may have a bad
            # checksum.  Permit a few identity-only retries, with no reads of
            # radio memory and no transition into download/upload logic.
            for ident_try in range(1, 5):
                radio._write_record(0x80)  # CMD_ID
                checksum_error, resp = radio._read_record()
                saw_record = True
                last_resp = bytes(resp or b"")
                responses.append({
                    "try": ident_try,
                    "checksumError": bool(checksum_error),
                    "responseHex": last_resp.hex(),
                    "responseBytes": len(last_resp),
                })
                if checksum_error:
                    time.sleep(0.100)
                    continue
                if last_resp[:len(expected)] == expected:
                    matched = True
                break

            if saw_record:
                radio._finish()  # CMD_END, source-audited driver exit
                finish_sent = True

            attempts.append({
                "vendorFamily": "Wouxun KG-UV8E",
                "baud": baud,
                "command": "CMD_ID",
                "expectedModelHex": expected.hex(),
                "expectedModelAscii": "".join(
                    chr(b) if 32 <= b < 127 else "." for b in expected),
                "responses": responses,
                "resetMode": reset_mode,
                "finishCommand": "CMD_END",
                "finishSent": finish_sent,
            })

            if not matched:
                continue

            match = _candidate_dict(entry, cls, "kguv8e")
            return {
                "matched": True,
                "confidence": "high",
                "family": "Wouxun KG-UV8E",
                "suggested": match,
                "candidates": [match],
                "attempts": attempts,
                "identity": {
                    "responseHex": last_resp.hex(),
                    "modelHex": expected.hex(),
                    "modelAscii": "".join(
                        chr(b) if 32 <= b < 127 else "." for b in expected),
                },
            }
        except Exception as e:
            # Only send CMD_END if a genuine framed response was received.
            if saw_record and not finish_sent:
                try:
                    radio._finish()
                    finish_sent = True
                except Exception:
                    pass
            attempts.append({
                "vendorFamily": "Wouxun KG-UV8E",
                "baud": baud,
                "command": "CMD_ID",
                "responses": responses,
                "responseHex": last_resp.hex(),
                "resetMode": reset_mode,
                "finishCommand": "CMD_END",
                "finishSent": finish_sent,
                "error": "%s: %s" % (e.__class__.__name__, e),
            })

    return {"matched": False, "attempts": attempts}


def _safe_priority_protocol_probe_result(java_transport):
    """Targeted safe protocols that must run before broad native detectors."""
    all_attempts = []
    for fn in (_safe_probe_radioddity_gm30, _safe_probe_kguv8e):
        result = fn(java_transport)
        all_attempts.extend(result.get("attempts") or [])
        if result.get("matched"):
            result["vendorAttempts"] = all_attempts
            return result
    return {"matched": False, "attempts": all_attempts}

def _safe_probe_icom_clone_id(java_transport):
    """Generic Icom clone-mode CLONE_ID query.

    Uses only the all-zero CLONE_ID payload supported by ordinary Icom
    clone-mode radios. Drivers which explicitly require a model-bearing ID
    query are excluded because probing those would require guessing a model.
    """
    try:
        from chirp.drivers import icf
    except Exception:
        return {"matched": False, "attempts": []}

    by_baud = {}
    for entry in (_radio_catalog_cache.get("radios") or []) if _radio_catalog_cache else []:
        try:
            cls = _find_loaded_radio_class(entry)
            if not issubclass(cls, icf.IcomCloneModeRadio):
                continue
            if bool(getattr(cls, "_id_query_with_model", False)):
                continue
            model = cls.get_model()
            if not isinstance(model, (bytes, bytearray)) or len(model) != 4:
                continue
            model = bytes(model)
            if model == b"\x00\x00\x00\x00":
                continue
            baud = int(getattr(cls, "BAUDRATE", getattr(cls, "BAUD_RATE", 9600)) or 9600)
            by_baud.setdefault(baud, []).append((entry, cls, model))
        except Exception:
            continue

    attempts = []
    for baud, candidates in sorted(by_baud.items(), key=lambda x: (0 if x[0] == 9600 else 1, x[0])):
        try:
            reset_mode = _probe_reset(java_transport, baud, "icom:clone-id")
            pipe = LegacyAndroidSerialPipe(java_transport)
            pipe.baudrate = baud
            pipe.timeout = 0.9
            pipe.reset_input_buffer()

            class _IcomProbe:
                # get_model_data/send_clone_frame requires get_payload().
                # Delegate to CHIRP's actual Icom clone-mode implementation
                # rather than reproducing the frame encoding here.
                _raw_frames = False

                def __init__(self, p):
                    self.pipe = p

                def get_payload(self, data, raw, checksum):
                    return icf.IcomCloneModeRadio.get_payload(
                        self, data, raw, checksum)

            probe = _IcomProbe(pipe)
            stream = icf.RadioStream(pipe)
            md = bytes(icf.get_model_data(
                probe, mdata=b"\x00\x00\x00\x00", stream=stream))
            attempt = {
                "vendorFamily": "Icom clone-mode",
                "baud": baud,
                "responseHex": md.hex(),
                "responseBytes": len(md),
                "resetMode": reset_mode,
            }
            attempts.append(attempt)
            if len(md) < 4:
                continue

            code = md[:4]
            matches = []
            for entry, cls, model in candidates:
                if code == model:
                    matches.append({
                        "key": entry.get("key", ""),
                        "vendor": entry.get("vendor", ""),
                        "model": entry.get("model", ""),
                        "variant": entry.get("variant", "") or "",
                        "module": entry.get("module", ""),
                        "class": entry.get("class", "") or cls.__name__,
                    })
            if matches:
                suggested = matches[0] if len(matches) == 1 else {
                    "vendor": "Icom",
                    "model": "Icom clone-mode family",
                    "variant": "",
                    "module": "icf",
                    "class": "",
                    "familyCandidateCount": len(matches),
                }
                return {
                    "matched": True,
                    "confidence": "high" if len(matches) == 1 else "family-high",
                    "family": "Icom clone-mode",
                    "suggested": suggested,
                    "candidates": matches,
                    "attempts": attempts,
                    "identity": {
                        "modelCodeHex": code.hex(),
                        "fullModelDataHex": md.hex(),
                    },
                }
        except Exception as e:
            attempts.append({
                "vendorFamily": "Icom clone-mode",
                "baud": baud,
                "error": "%s: %s" % (e.__class__.__name__, e),
            })

    return {"matched": False, "attempts": attempts}


def _safe_probe_radtel_t18(java_transport):
    """Radtel/Retevis T18-derived short ID sequence, then explicit exit."""
    probes = {}
    for entry in (_radio_catalog_cache.get("radios") or []) if _radio_catalog_cache else []:
        try:
            cls = _find_loaded_radio_class(entry)
            if str(getattr(cls, "__module__", "")).split(".")[-1] != "radtel_t18":
                continue
            magic = getattr(cls, "_magic", None)
            fps = getattr(cls, "_fingerprint", None)
            if not isinstance(magic, (bytes, bytearray)) or not isinstance(fps, (list, tuple)):
                continue
            fpvals = [bytes(x) for x in fps if isinstance(x, (bytes, bytearray))]
            if not fpvals:
                continue
            baud = int(getattr(cls, "BAUD_RATE", 9600) or 9600)
            probes.setdefault((baud, bytes(magic)), []).append((entry, cls, fpvals))
        except Exception:
            continue

    attempts = []
    for (baud, magic), candidates in sorted(probes.items(), key=lambda x: (-len(x[1]), x[0][1])):
        reset_mode = "reset-not-started"
        try:
            reset_mode = _probe_reset(java_transport, baud, "radtel_t18:model-ident")
            java_transport.setSerialParameters(baud, 8, 1.0, "N")
            _set_transport_timeout_ms(java_transport, 550)
            java_transport.setWriteTimeoutMs(450)
            java_transport.clearInputBuffer()

            entry_tx = b"\x02" + magic
            ack, entry_echo = _probe_write_read(
                java_transport, entry_tx, expected_min=1,
                timeout_s=0.68, max_bytes=24)
            ack = ack[:1]
            if ack != b"\x06":
                attempts.append({
                    "vendorFamily": "Radtel T18-derived",
                    "baud": baud,
                    "magicHex": magic.hex(),
                    "ackHex": ack.hex(),
                    "resetMode": reset_mode,
                    "echoInfo": entry_echo,
                })
                continue

            ident, ident_echo = _probe_write_read(
                java_transport, b"\x02", expected_min=8,
                timeout_s=0.76, max_bytes=24)
            ident = ident[:8]

            matches = []
            for entry, cls, fps in candidates:
                if any(ident.startswith(fp) for fp in fps):
                    matches.append({
                        "key": entry.get("key", ""),
                        "vendor": entry.get("vendor", ""),
                        "model": entry.get("model", ""),
                        "variant": entry.get("variant", "") or "",
                        "module": entry.get("module", "") or "radtel_t18",
                        "class": entry.get("class", "") or cls.__name__,
                    })

            # Complete CHIRP's handshake and explicitly leave programming mode.
            java_transport.writeBytes(b"\x06")
            _transport_read_exact(java_transport, 1, 0.35)
            exit_cmd = getattr(candidates[0][1], "CMD_EXIT", None)
            if isinstance(exit_cmd, (bytes, bytearray)) and exit_cmd:
                java_transport.writeBytes(bytes(exit_cmd))

            attempts.append({
                "vendorFamily": "Radtel T18-derived",
                "baud": baud,
                "magicHex": magic.hex(),
                "identHex": ident.hex(),
                "resetMode": reset_mode,
            })

            if matches:
                suggested = matches[0] if len(matches) == 1 else {
                    "vendor": "",
                    "model": "Radtel/T18-derived family",
                    "variant": "",
                    "module": "radtel_t18",
                    "class": "",
                    "familyCandidateCount": len(matches),
                }
                return {
                    "matched": True,
                    "confidence": "high" if len(matches) == 1 else "family-high",
                    "family": "Radtel/T18-derived",
                    "suggested": suggested,
                    "candidates": matches,
                    "attempts": attempts,
                    "identity": {"identHex": ident.hex()},
                }
        except Exception as e:
            attempts.append({
                "vendorFamily": "Radtel T18-derived",
                "baud": baud,
                "magicHex": magic.hex(),
                "resetMode": reset_mode,
                "error": "%s: %s" % (e.__class__.__name__, e),
            })

    return {"matched": False, "attempts": attempts}


def _safe_probe_radtel_rt490(java_transport):
    """Radtel RT-490 short program ACK + 8-byte F-ident + explicit E exit."""
    entries = []
    for entry in (_radio_catalog_cache.get("radios") or []) if _radio_catalog_cache else []:
        try:
            cls = _find_loaded_radio_class(entry)
            if str(getattr(cls, "__module__", "")).split(".")[-1] != "radtel_rt490":
                continue
            magic = getattr(cls, "_magic", None)
            fp = getattr(cls, "_fingerprint", None)
            if isinstance(magic, (bytes, bytearray)) and isinstance(fp, (bytes, bytearray)):
                entries.append((entry, cls, bytes(magic), bytes(fp)))
        except Exception:
            continue

    # All RT490-derived aliases currently share one short wire identity; this
    # detector therefore reports the exact CHIRP branch, but may remain family
    # level across aliases if multiple catalog entries share the fingerprint.
    grouped = {}
    for item in entries:
        entry, cls, magic, fp = item
        baud = int(getattr(cls, "BAUD_RATE", 9600) or 9600)
        grouped.setdefault((baud, magic), []).append(item)

    attempts = []
    for (baud, magic), candidates in grouped.items():
        reset_mode = "reset-not-started"
        try:
            reset_mode = _probe_reset(java_transport, baud, "radtel_rt490:model-ident")
            java_transport.setSerialParameters(baud, 8, 1.0, "N")
            _set_transport_timeout_ms(java_transport, 550)
            java_transport.setWriteTimeoutMs(450)
            java_transport.clearInputBuffer()

            ack, entry_echo = _probe_write_read(
                java_transport, magic, expected_min=1,
                timeout_s=0.68, max_bytes=24)
            ack = ack[:1]
            if ack != b"\x06":
                continue
            ident, ident_echo = _probe_write_read(
                java_transport, b"F", expected_min=8,
                timeout_s=0.76, max_bytes=24)
            ident = ident[:8]
            try:
                java_transport.writeBytes(b"E")
            except Exception:
                pass

            matches = []
            for entry, cls, _magic, fp in candidates:
                if ident.startswith(fp):
                    matches.append({
                        "key": entry.get("key", ""),
                        "vendor": entry.get("vendor", ""),
                        "model": entry.get("model", ""),
                        "variant": entry.get("variant", "") or "",
                        "module": entry.get("module", "") or "radtel_rt490",
                        "class": entry.get("class", "") or cls.__name__,
                    })
            attempts.append({
                "vendorFamily": "Radtel RT-490-derived",
                "baud": baud,
                "identHex": ident.hex(),
                "resetMode": reset_mode,
            })
            if matches:
                suggested = matches[0] if len(matches) == 1 else {
                    "vendor": "Radtel",
                    "model": "RT-490-derived family",
                    "variant": "",
                    "module": "radtel_rt490",
                    "class": "",
                    "familyCandidateCount": len(matches),
                }
                return {
                    "matched": True,
                    "confidence": "high" if len(matches) == 1 else "family-high",
                    "family": "Radtel RT-490-derived",
                    "suggested": suggested,
                    "candidates": matches,
                    "attempts": attempts,
                    "identity": {"identHex": ident.hex()},
                }
        except Exception as e:
            attempts.append({
                "vendorFamily": "Radtel RT-490-derived",
                "baud": baud,
                "resetMode": reset_mode,
                "error": "%s: %s" % (e.__class__.__name__, e),
            })

    return {"matched": False, "attempts": attempts}



def _safe_probe_program_qx_family(java_transport):
    """Safe legacy PROGRAM/QX06/02 identity sequence with explicit END.

    Source-audited modules:
      anytone, anytone_ht, anytone_iii, retevis_rt98, th9000

    The driver protocol echoes each command, so this helper consumes the echo,
    reads only the 16-byte version/identity response, then sends END.
    """
    modules = {"anytone", "anytone_ht", "anytone_iii", "retevis_rt98", "th9000"}
    candidates = []
    for entry in (_radio_catalog_cache.get("radios") or []) if _radio_catalog_cache else []:
        try:
            cls = _find_loaded_radio_class(entry)
            module = str(getattr(cls, "__module__", "")).split(".")[-1]
            if module in modules:
                candidates.append((entry, cls, module))
        except Exception:
            continue
    if not candidates:
        return {"matched": False, "attempts": []}

    attempts = []
    # All source-audited classes in this family use 9600.
    try:
        reset_mode = _probe_reset(java_transport, 9600, "program-qx:identity")
        java_transport.setSerialParameters(9600, 8, 1.0, "N")
        _set_transport_timeout_ms(java_transport, 650)
        java_transport.setWriteTimeoutMs(450)
        java_transport.clearInputBuffer()

        def echo_write(data):
            java_transport.writeBytes(data)
            echo = _transport_read_exact(java_transport, len(data), 0.55)
            if echo != data:
                raise RuntimeError(
                    "PROGRAM/QX identity command echo mismatch")

        echo_write(b"PROGRAM")
        qx = _transport_read_exact(java_transport, 3, 0.65)
        if qx != b"QX\x06":
            return {
                "matched": False,
                "attempts": [{
                    "vendorFamily": "PROGRAM/QX",
                    "resetMode": reset_mode,
                    "responseHex": qx.hex(),
                }],
            }

        echo_write(b"\x02")
        ident = _transport_read_exact(java_transport, 16, 0.80)

        # Always use the driver's explicit finish sequence.
        try:
            echo_write(b"END")
            finish_ack = _transport_read_exact(java_transport, 1, 0.45)
        except Exception:
            finish_ack = b""

        matches = []
        for entry, cls, module in candidates:
            hit = False
            if module in ("anytone", "anytone_ht", "anytone_iii"):
                fid = getattr(cls, "_file_ident", None)
                vals = fid if isinstance(fid, (list, tuple)) else [fid]
                vals = [bytes(x) for x in vals
                        if isinstance(x, (bytes, bytearray))]
                hit = any(v and v in ident for v in vals)
            elif module == "th9000":
                hit = ident[1:8] == b"TH-9000"
            elif module == "retevis_rt98":
                try:
                    allowed = getattr(cls, "ALLOWED_RADIO_TYPES", {})
                    from chirp.drivers import retevis_rt98 as _rt98
                    ok, _model, _band = _rt98.check_ver(ident, allowed)
                    hit = bool(ok)
                except Exception:
                    hit = False

            if hit:
                matches.append({
                    "key": entry.get("key", ""),
                    "vendor": entry.get("vendor", ""),
                    "model": entry.get("model", ""),
                    "variant": entry.get("variant", "") or "",
                    "module": entry.get("module", "") or module,
                    "class": entry.get("class", "") or cls.__name__,
                })

        if not matches:
            return {
                "matched": False,
                "attempts": [{
                    "vendorFamily": "PROGRAM/QX",
                    "resetMode": reset_mode,
                    "responseHex": ident.hex(),
                    "finishAckHex": finish_ack.hex(),
                }],
            }

        # TH-9000 band variants intentionally remain a candidate set because
        # the 16-byte ident is only a family signature in CHIRP.
        suggested = matches[0] if len(matches) == 1 else {
            "vendor": "",
            "model": "PROGRAM/QX identified family",
            "variant": "",
            "module": "program_qx",
            "class": "",
            "familyCandidateCount": len(matches),
        }
        return {
            "matched": True,
            "confidence": "high" if len(matches) == 1 else "family-high",
            "family": "PROGRAM/QX clone family",
            "suggested": suggested,
            "candidates": matches,
            "attempts": [{
                "vendorFamily": "PROGRAM/QX",
                "resetMode": reset_mode,
                "responseHex": ident.hex(),
                "finishAckHex": finish_ack.hex(),
            }],
            "identity": {
                "identHex": ident.hex(),
                "identAscii": "".join(
                    chr(b) if 32 <= b < 127 else "." for b in ident),
            },
        }
    except Exception as e:
        return {
            "matched": False,
            "attempts": [{
                "vendorFamily": "PROGRAM/QX",
                "error": "%s: %s" % (e.__class__.__name__, e),
            }],
        }



def _safe_vendor_probe_result(java_transport):
    """Additional source-audited vendor detectors, all fail-closed."""
    all_attempts = []

    for fn in (
        _safe_probe_icom_clone_id,
        _safe_probe_wouxun,
        _safe_probe_radtel_t18,
        _safe_probe_radtel_rt490,
        _safe_probe_program_qx_family,
    ):
        result = fn(java_transport)
        all_attempts.extend(result.get("attempts") or [])
        if result.get("matched"):
            result["vendorAttempts"] = all_attempts
            return result

    return {
        "matched": False,
        "attempts": all_attempts,
    }



def _radio_auto_detection_coverage():
    """Classify every bundled catalog module under a fail-closed safety policy."""
    modules = {}
    if _radio_catalog_cache is None:
        return {"modules": [], "summary": {}}

    for entry in (_radio_catalog_cache.get("radios") or []):
        module = str(entry.get("module") or "").split(".")[-1]
        if not module:
            continue
        row = modules.setdefault(module, {
            "module": module,
            "radioCount": 0,
            "mode": "SKIP_UNVETTED",
            "reason": "No source-audited non-destructive auto-detect recipe enabled",
        })
        row["radioCount"] += 1

    for module, row in modules.items():
        if module in _SAFE_NATIVE_MODULES:
            row["mode"] = "AUTO_NATIVE_SAFE"
            row["reason"] = "CHIRP detect_from_serial wrapped by strict identification-only byte/time budgets"
        elif module in _SAFE_VENDOR_MODULES or module.startswith("ic"):
            row["mode"] = "AUTO_VENDOR_SAFE"
            row["reason"] = "Source-audited vendor/model identity query with no image or channel transfer"
        elif module in _SAFE_FAST_MODULES:
            row["mode"] = "AUTO_HANDSHAKE_SAFE"
            row["reason"] = "Source-audited first-stage request with explicit expected response"

    rows = sorted(modules.values(), key=lambda r: r["module"])
    summary = {
        "moduleCount": len(rows),
        "nativeSafe": sum(r["mode"] == "AUTO_NATIVE_SAFE" for r in rows),
        "vendorSafe": sum(r["mode"] == "AUTO_VENDOR_SAFE" for r in rows),
        "handshakeSafe": sum(r["mode"] == "AUTO_HANDSHAKE_SAFE" for r in rows),
        "skippedUnvetted": sum(r["mode"] == "SKIP_UNVETTED" for r in rows),
    }
    summary["enabledSafe"] = (
        summary["nativeSafe"] + summary["vendorSafe"] + summary["handshakeSafe"]
    )
    return {"modules": rows, "summary": summary}





def radio_auto_probe_json(java_transport, transport_kind="unknown"):
    """Read-only radio auto-detection using source-audited sequence recipes."""

    # Stage 1: the two strongest dynamic detectors seen in modern radios.
    native_primary = _native_detect_result(
        java_transport, include_modules={"uvk5", "tdh8"})
    if native_primary.get("matched"):
        return _json.dumps({
            "version": 7,
            "mode": "chirp-driver-radio-auto-probe",
            "transport": str(transport_kind),
            "strategy": "sequence-aware-safe-autodetect",
            "safety": "Fail-closed source-audited identity sequences only; no sync_in, sync_out, channel/image download, or memory writes",
            "confidence": native_primary.get("confidence", "high"),
            "suggested": native_primary.get("suggested"),
            "nativeAttempts": native_primary.get("attempts") or [],
            "sequenceStage": "native-primary",
            "attemptCount": len(native_primary.get("attempts") or []),
            "responseCount": 1,
            "rankedCandidates": [native_primary.get("suggested")] if native_primary.get("suggested") else [],
            "likelyCandidates": [native_primary.get("suggested")] if native_primary.get("suggested") else [],
            "responses": [],
            "attempts": [],
            "coverageSummary": _radio_auto_detection_coverage().get("summary") or {},
            "resetInfo": _probe_reset_info(java_transport),
        }, separators=(",", ":"))

    # Stage 2: proven UV-82/UV5R gateway. If it ACKs, do not reset; continue
    # exact identity from the live program-ACK session.
    uv = _safe_probe_uv5r_priority(java_transport)
    if uv.get("matched"):
        discriminator = _safe_family_discriminator(java_transport, uv)
        exact_suggested = discriminator.get("suggested") if discriminator else None
        exact_matches = (discriminator.get("matches") or []) if discriminator else []
        final_suggested = exact_suggested or uv.get("suggested")
        final_candidates = exact_matches or (uv.get("candidates") or [])
        final_confidence = (
            discriminator.get("confidence")
            if discriminator and exact_suggested
            else uv.get("confidence", "family-high")
        )
        return _json.dumps({
            "version": 7,
            "mode": "chirp-driver-radio-auto-probe",
            "transport": str(transport_kind),
            "strategy": "sequence-aware-safe-autodetect",
            "safety": "Fail-closed source-audited identity sequences only; no sync_in, sync_out, channel/image download, or memory writes",
            "confidence": final_confidence,
            "family": uv.get("family"),
            "suggested": final_suggested,
            "familyCandidates": uv.get("candidates") or [],
            "modelDiscriminator": discriminator,
            "sequenceStage": "uv5r-live-session-continuation",
            "nativeAttempts": native_primary.get("attempts") or [],
            "vendorAttempts": [],
            "attemptCount": len(native_primary.get("attempts") or []) + 1,
            "responseCount": 1,
            "rankedCandidates": final_candidates,
            "likelyCandidates": final_candidates[:10],
            "responses": [uv.get("match")] if uv.get("match") else [],
            "attempts": [],
            "coverageSummary": _radio_auto_detection_coverage().get("summary") or {},
            "resetInfo": _probe_reset_info(java_transport),
        }, separators=(",", ":"))

    # Stage 3: targeted source-audited protocols which must run before the
    # broader remaining native detectors.  In particular, ga510's detector
    # also tries the GM-30 PSEARCH handshake and can continue after a valid
    # P13GMRS response, leaving that radio in programming mode.
    priority_vendor = _safe_priority_protocol_probe_result(java_transport)
    if priority_vendor.get("matched"):
        final_candidates = priority_vendor.get("candidates") or []
        return _json.dumps({
            "version": 7,
            "mode": "chirp-driver-radio-auto-probe",
            "transport": str(transport_kind),
            "strategy": "sequence-aware-safe-autodetect",
            "safety": "Fail-closed source-audited identity sequences only; no sync_in, sync_out, channel/image download, or memory writes",
            "confidence": priority_vendor.get("confidence", "high"),
            "family": priority_vendor.get("family"),
            "suggested": priority_vendor.get("suggested"),
            "familyCandidates": final_candidates,
            "vendorAttempts": priority_vendor.get("vendorAttempts") or priority_vendor.get("attempts") or [],
            "nativeAttempts": native_primary.get("attempts") or [],
            "sequenceStage": "priority-safe-protocol",
            "attemptCount": (
                len(native_primary.get("attempts") or [])
                + len(priority_vendor.get("vendorAttempts") or priority_vendor.get("attempts") or [])
            ),
            "responseCount": 1,
            "rankedCandidates": final_candidates,
            "likelyCandidates": final_candidates[:10],
            "responses": [],
            "attempts": [],
            "coverageSummary": _radio_auto_detection_coverage().get("summary") or {},
            "resetInfo": _probe_reset_info(java_transport),
        }, separators=(",", ":"))

    # Stage 4: remaining CHIRP-native safe detectors.
    native_rest = _native_detect_result(
        java_transport, exclude_modules={"uvk5", "tdh8"})
    if native_rest.get("matched"):
        all_native = (
            (native_primary.get("attempts") or [])
            + (native_rest.get("attempts") or [])
        )
        return _json.dumps({
            "version": 7,
            "mode": "chirp-driver-radio-auto-probe",
            "transport": str(transport_kind),
            "strategy": "sequence-aware-safe-autodetect",
            "safety": "Fail-closed source-audited identity sequences only; no sync_in, sync_out, channel/image download, or memory writes",
            "confidence": native_rest.get("confidence", "high"),
            "suggested": native_rest.get("suggested"),
            "nativeAttempts": all_native,
            "vendorAttempts": priority_vendor.get("attempts") or [],
            "sequenceStage": "native-secondary",
            "attemptCount": len(all_native) + len(priority_vendor.get("attempts") or []),
            "responseCount": 1,
            "rankedCandidates": [native_rest.get("suggested")] if native_rest.get("suggested") else [],
            "likelyCandidates": [native_rest.get("suggested")] if native_rest.get("suggested") else [],
            "responses": [],
            "attempts": [],
            "coverageSummary": _radio_auto_detection_coverage().get("summary") or {},
            "resetInfo": _probe_reset_info(java_transport),
        }, separators=(",", ":"))

    # Stage 5: explicit vendor/model sequences with known exits or pure ID query.
    vendor = _safe_vendor_probe_result(java_transport)
    if vendor.get("matched"):
        final_candidates = vendor.get("candidates") or []
        return _json.dumps({
            "version": 7,
            "mode": "chirp-driver-radio-auto-probe",
            "transport": str(transport_kind),
            "strategy": "sequence-aware-safe-autodetect",
            "safety": "Fail-closed source-audited identity sequences only; no sync_in, sync_out, channel/image download, or memory writes",
            "confidence": vendor.get("confidence", "family-high"),
            "family": vendor.get("family"),
            "suggested": vendor.get("suggested"),
            "familyCandidates": final_candidates,
            "vendorAttempts": (
                (priority_vendor.get("attempts") or [])
                + (vendor.get("vendorAttempts") or vendor.get("attempts") or [])
            ),
            "nativeAttempts": (
                (native_primary.get("attempts") or [])
                + (native_rest.get("attempts") or [])
            ),
            "sequenceStage": "vendor-safe-sequence",
            "attemptCount": (
                len(native_primary.get("attempts") or [])
                + len(priority_vendor.get("attempts") or [])
                + len(native_rest.get("attempts") or [])
                + len(vendor.get("vendorAttempts") or vendor.get("attempts") or [])
            ),
            "responseCount": 1,
            "rankedCandidates": final_candidates,
            "likelyCandidates": final_candidates[:10],
            "responses": [],
            "attempts": [],
            "coverageSummary": _radio_auto_detection_coverage().get("summary") or {},
            "resetInfo": _probe_reset_info(java_transport),
        }, separators=(",", ":"))

    # Stage 6: remaining vetted safe family gateways.
    fast = _fast_family_probe_result(java_transport)
    if fast.get("matched"):
        discriminator = _safe_family_discriminator(java_transport, fast)
        exact_suggested = discriminator.get("suggested") if discriminator else None
        exact_matches = (discriminator.get("matches") or []) if discriminator else []
        final_suggested = exact_suggested or fast.get("suggested")
        final_candidates = exact_matches or (fast.get("candidates") or [])
        final_confidence = (
            discriminator.get("confidence")
            if discriminator and exact_suggested
            else fast.get("confidence", "family-high")
        )
        return _json.dumps({
            "version": 7,
            "mode": "chirp-driver-radio-auto-probe",
            "transport": str(transport_kind),
            "strategy": "sequence-aware-safe-autodetect",
            "safety": "Fail-closed source-audited identity sequences only; no sync_in, sync_out, channel/image download, or memory writes",
            "confidence": final_confidence,
            "family": fast.get("family"),
            "suggested": final_suggested,
            "familyCandidates": fast.get("candidates") or [],
            "modelDiscriminator": discriminator,
            "fastFamilyAttempts": fast.get("attempts") or [],
            "sequenceStage": "safe-family-fallback",
            "nativeAttempts": (
                (native_primary.get("attempts") or [])
                + (native_rest.get("attempts") or [])
            ),
            "vendorAttempts": (
                (priority_vendor.get("attempts") or [])
                + (vendor.get("attempts") or [])
            ),
            "attemptCount": (
                len(native_primary.get("attempts") or [])
                + len(priority_vendor.get("attempts") or [])
                + len(native_rest.get("attempts") or [])
                + len(vendor.get("attempts") or [])
                + len(fast.get("attempts") or [])
            ),
            "responseCount": 1,
            "rankedCandidates": final_candidates,
            "likelyCandidates": final_candidates[:10],
            "responses": [fast.get("match")] if fast.get("match") else [],
            "attempts": [],
            "coverageSummary": _radio_auto_detection_coverage().get("summary") or {},
            "resetInfo": _probe_reset_info(java_transport),
        }, separators=(",", ":"))

    coverage = _radio_auto_detection_coverage()
    all_native = (
        (native_primary.get("attempts") or [])
        + (native_rest.get("attempts") or [])
    )
    return _json.dumps({
        "version": 7,
        "mode": "chirp-driver-radio-auto-probe",
        "transport": str(transport_kind),
        "strategy": "sequence-aware-safe-autodetect",
        "safety": "Fail-closed source-audited identity sequences only; no sync_in, sync_out, channel/image download, or memory writes",
        "confidence": "none",
        "suggested": None,
        "family": None,
        "nativeAttempts": all_native,
        "vendorAttempts": (
            (priority_vendor.get("attempts") or [])
            + (vendor.get("attempts") or [])
        ),
        "fastFamilyAttempts": fast.get("attempts") or [],
        "sequenceStage": "no-safe-match",
        "attemptCount": (
            len(all_native)
            + len(priority_vendor.get("attempts") or [])
            + len(vendor.get("attempts") or [])
            + len(fast.get("attempts") or [])
        ),
        "responseCount": 0,
        "rankedCandidates": [],
        "likelyCandidates": [],
        "responses": [],
        "attempts": [],
        "coverageSummary": coverage.get("summary") or {},
        "resetInfo": _probe_reset_info(java_transport),
        "skippedReason": "No source-audited safe sequence matched; unvetted driver families were not probed",
    }, separators=(",", ":"))

def selected_radio_prompt_contract_json(kind):
    """Return the selected CHIRP driver's complete RadioPrompts contract.

    PocketCHIRP treats RadioPrompts as part of the driver contract, not as
    desktop-only decoration.  The fields currently used by CHIRP drivers are
    preserved here: pre_download, pre_upload, experimental, info, and
    display_pre_upload_prompt_before_opening_port.
    """
    cls = _selected_class()
    try:
        prompts = cls.get_prompts()
    except Exception as exc:
        return _json.dumps({
            "vendor": str(getattr(cls, "VENDOR", "") or ""),
            "model": str(getattr(cls, "MODEL", "") or ""),
            "kind": str(kind or ""),
            "pre": "",
            "pre_download": "",
            "pre_upload": "",
            "experimental": "",
            "info": "",
            "display_pre_upload_prompt_before_opening_port": True,
            "error": "%s: %s" % (exc.__class__.__name__, exc),
        }, separators=(",", ":"))

    # Return raw CHIRP prompt text. Android/UI formatting is proprietary
    # PocketCHIRP presentation policy and is applied by PocketChirpPromptFormatter.
    pre_download = str(getattr(prompts, "pre_download", "") or "")
    pre_upload = str(getattr(prompts, "pre_upload", "") or "")
    experimental = str(getattr(prompts, "experimental", "") or "")
    info = str(getattr(prompts, "info", "") or "")
    upload_before_open = bool(getattr(
        prompts, "display_pre_upload_prompt_before_opening_port", True))
    is_upload = str(kind or "").lower().startswith("up")
    return _json.dumps({
        "vendor": str(getattr(cls, "VENDOR", "") or ""),
        "model": str(getattr(cls, "MODEL", "") or ""),
        "kind": "upload" if is_upload else "download",
        "pre": pre_upload if is_upload else pre_download,
        "pre_download": pre_download,
        "pre_upload": pre_upload,
        "experimental": experimental,
        "info": info,
        "display_pre_upload_prompt_before_opening_port": upload_before_open,
        "error": "",
    }, separators=(",", ":"))





def download_selected_editor_once_result_json(java_transport, attempt=1,
                                              transport_kind="unknown"):
    cls = _selected_class()
    vendor = str(getattr(cls, "VENDOR", "") or "")
    model = str(getattr(cls, "MODEL", "") or "")
    try:
        result = download_selected_editor(
            java_transport, physical_transport_kind=transport_kind)
        return _json.dumps({
            "ok": True,
            "attempt": int(attempt or 1),
            "result": str(result or ""),
            "error": "",
            "errorType": "",
            "vendor": vendor,
            "model": model,
            "transport": str(transport_kind or ""),
        }, separators=(",", ":"))
    except Exception as exc:
        return _json.dumps({
            "ok": False,
            "attempt": int(attempt or 1),
            "result": "",
            "error": str(exc) or exc.__class__.__name__,
            "errorType": exc.__class__.__name__,
            "vendor": vendor,
            "model": model,
            "transport": str(transport_kind or ""),
        }, separators=(",", ":"))




# =============================================================================
# POCKETCHIRP GENERIC CHIRP LiveRadio ADAPTER — BRIDGE-ONLY / ADDITIVE
# =============================================================================
# WHY:
# CHIRP has two fundamentally different programming models:
#   * CloneModeRadio: sync_in() downloads an image, editing happens offline,
#     sync_out() writes the image back.
#   * LiveRadio: get_memory()/set_memory()/erase_memory() talk to the physical
#     radio immediately.  Desktop CHIRP keeps the serial session live while the
#     user edits.
#
# PocketCHIRP's editor is intentionally image/offline based.  Calling a real
# LiveRadio from editor functions would therefore make Insert/Move/Undo perform
# immediate hardware writes.  This adapter creates a PRIVATE, detached JSON
# snapshot which implements the same CHIRP memory interface in RAM.  Existing
# editor code can edit that proxy safely.  Only the explicit Read and Write
# actions below ever instantiate a real LiveRadio with an AndroidSerialPipe.
#
# HARD REGRESSION BOUNDARY:
#   * No existing CloneModeRadio read/write function is replaced.
#   * No BLE resolver, Yaesu sequencing, native USB adapter, clone block size,
#     serial framing, or transport I/O method is modified.
#   * The new route is selected ONLY by issubclass(cls, chirp_common.LiveRadio)
#     or by the exact PocketCHIRP Live Snapshot magic below.
#   * LiveRadio settings are deliberately NOT staged yet.  A driver's memory
#     API is supported; direct radio-wide set_settings() is kept unavailable so
#     the offline editor can never apply a setting while merely rendering.
#   * Per-memory `extra` objects that cannot be represented losslessly are
#     preserved as a write-safety marker; editing such a memory is fail-closed.
#
# WEBCHIRP NOTE:
# WebCHIRP already classifies catalog entries with isLiveRadio but currently
# disables its connect/read/write controls for them.  PocketCHIRP uses the same
# CHIRP class distinction, but adds the detached snapshot/commit layer here.
#
# EASY REVERT:
# Remove this entire section and the small LiveRadio branches in
# download_selected_editor(), backup_connected_radio_once_bytes(),
# _metadata_for_image(), _radio_from_image_bytes(), and controlled_write_*().
# The historical CloneModeRadio code then executes exactly as before.
# =============================================================================

_LIVE_SNAPSHOT_MAGIC = b"POCKETCHIRP-LIVERADIO-V1\n"
_LIVE_SNAPSHOT_SCHEMA = 1


def _is_live_snapshot_bytes(data):
    try:
        return bytes(data or b"").startswith(_LIVE_SNAPSHOT_MAGIC)
    except Exception:
        return False


def _live_json_safe(value):
    """Return a JSON-safe primitive/container, or (False, None) if opaque."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return True, value
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            ok, safe = _live_json_safe(item)
            if not ok:
                return False, None
            out.append(safe)
        return True, out
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, (str, int, float, bool)):
                return False, None
            ok, safe = _live_json_safe(item)
            if not ok:
                return False, None
            out[str(key)] = safe
        return True, out
    return False, None


def _live_feature_record(rf):
    """Capture only driver-declared feature values needed by the existing editor."""
    bool_names = (
        "has_bank", "has_settings", "has_name", "has_offset", "has_mode",
        "has_tuning_step", "has_nostep_tuning", "has_ctone", "has_rtone",
        "has_tone", "has_dtcs", "has_rx_dtcs", "has_tx_dtcs",
        "has_dtcs_polarity", "has_cross", "has_comment", "has_sub_devices",
        "can_odd_split", "can_delete",
    )
    scalar_names = ("valid_name_length", "max_offset", "valid_characters")
    seq_names = (
        "valid_bands", "valid_modes", "valid_tmodes", "valid_duplexes",
        "valid_skips", "valid_cross_modes", "valid_tuning_steps", "valid_tones",
        "valid_dtcs_codes", "valid_special_chans",
    )
    out = {}
    for name in bool_names:
        try:
            out[name] = bool(getattr(rf, name))
        except Exception:
            pass
    for name in scalar_names:
        try:
            ok, val = _live_json_safe(getattr(rf, name))
            if ok:
                out[name] = val
        except Exception:
            pass
    for name in seq_names:
        try:
            ok, val = _live_json_safe(list(getattr(rf, name) or []))
            if ok:
                out[name] = val
        except Exception:
            pass
    try:
        out["memory_bounds"] = [int(rf.memory_bounds[0]), int(rf.memory_bounds[1])]
    except Exception:
        out["memory_bounds"] = [0, -1]
    try:
        out["valid_power_levels"] = [str(x) for x in (rf.valid_power_levels or [])]
    except Exception:
        out["valid_power_levels"] = []

    # Radio-wide settings cannot be safely detached with the current editor API:
    # get_settings()/set_settings() on LiveRadio may themselves do hardware I/O.
    # Hide that capability on the proxy rather than risking an implicit write.
    out["live_original_has_settings"] = bool(out.get("has_settings", False))
    out["has_settings"] = False
    # CHIRP itself does not provide a generic bank model for live radios.  Keep
    # bank manipulation disabled unless a future snapshot format explicitly
    # captures a live-safe bank contract.
    out["live_original_has_bank"] = bool(out.get("has_bank", False))
    out["has_bank"] = False
    return out


def _live_features_from_record(record):
    from chirp import chirp_common
    rf = chirp_common.RadioFeatures()
    record = dict(record or {})
    for name, value in record.items():
        if name.startswith("live_original_") or name == "valid_power_levels":
            continue
        try:
            if name == "memory_bounds":
                setattr(rf, name, (int(value[0]), int(value[1])))
            elif name == "valid_bands":
                setattr(rf, name, [tuple(int(x) for x in band) for band in value])
            else:
                setattr(rf, name, value)
        except Exception:
            pass
    powers = []
    for label in record.get("valid_power_levels", []) or []:
        try:
            powers.append(chirp_common.PowerLevel(str(label)))
        except Exception:
            pass
    try:
        rf.valid_power_levels = powers
    except Exception:
        pass
    try:
        rf.has_settings = False
        rf.has_bank = False
    except Exception:
        pass
    return rf


def _live_memory_token(key):
    if isinstance(key, str):
        return "s:" + key
    return "n:" + str(int(key))


def _live_memory_record(mem, requested_key):
    """Losslessly capture CHIRP's ordinary editable Memory fields where possible."""
    fields = (
        "number", "extd_number", "empty", "name", "freq", "duplex", "offset",
        "tmode", "rtone", "ctone", "dtcs", "rx_dtcs", "dtcs_polarity",
        "cross_mode", "mode", "skip", "tuning_step", "comment", "immutable",
        "tx_freq", "dv_urcall", "dv_rpt1call", "dv_rpt2call", "dv_code",
    )
    values = {}
    for name in fields:
        if not hasattr(mem, name):
            continue
        try:
            ok, val = _live_json_safe(getattr(mem, name))
            if ok:
                values[name] = val
        except Exception:
            pass
    try:
        power = getattr(mem, "power", None)
        values["power"] = "" if power is None else str(power)
    except Exception:
        values["power"] = ""

    known = set(fields) | {"power", "extra"}
    simple_extra_attrs = {}
    unsupported_attrs = []
    try:
        for name, value in vars(mem).items():
            if name.startswith("_") or name in known:
                continue
            ok, safe = _live_json_safe(value)
            if ok:
                simple_extra_attrs[name] = safe
            else:
                unsupported_attrs.append(name)
    except Exception:
        pass

    extra_ui = []
    try:
        extra_ui = _memory_extra_dict(mem)
    except Exception:
        extra_ui = []

    return {
        "requestedKey": requested_key,
        "memoryClass": mem.__class__.__name__,
        "values": values,
        "simpleExtraAttrs": simple_extra_attrs,
        # RadioSetting trees can contain callbacks/maps and cannot be guaranteed
        # to round-trip from JSON. Keep a diagnostic copy for the user, but mark
        # the memory fail-closed if an edit would require writing it.
        "extraUi": extra_ui,
        "extraUnsupported": bool(extra_ui),
        "unsupportedAttrs": sorted(set(unsupported_attrs)),
    }


def _live_memory_from_record(record, rf=None):
    from chirp import chirp_common
    rec = dict(record or {})
    cls_name = str(rec.get("memoryClass") or "Memory")
    mem_cls = chirp_common.DVMemory if cls_name == "DVMemory" and hasattr(chirp_common, "DVMemory") else chirp_common.Memory
    mem = mem_cls()
    values = dict(rec.get("values") or {})
    for name, value in values.items():
        if name == "power":
            continue
        try:
            setattr(mem, name, value)
        except Exception:
            pass
    for name, value in (rec.get("simpleExtraAttrs") or {}).items():
        try:
            setattr(mem, name, value)
        except Exception:
            pass
    requested_key = rec.get("requestedKey")
    if isinstance(requested_key, str):
        try:
            if not str(getattr(mem, "extd_number", "") or ""):
                mem.extd_number = requested_key
        except Exception:
            pass
    else:
        try:
            mem.number = int(requested_key)
        except Exception:
            pass

    power_label = str(values.get("power") or "")
    if power_label and rf is not None:
        try:
            for level in list(getattr(rf, "valid_power_levels", []) or []):
                if str(level) == power_label:
                    mem.power = level
                    break
        except Exception:
            pass
    return mem


def _live_snapshot_decode(data):
    raw = bytes(data or b"")
    if not raw.startswith(_LIVE_SNAPSHOT_MAGIC):
        raise ValueError("Not a PocketCHIRP LiveRadio snapshot")
    try:
        obj = _json.loads(raw[len(_LIVE_SNAPSHOT_MAGIC):].decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid PocketCHIRP LiveRadio snapshot") from exc
    if int(obj.get("schema", 0) or 0) != _LIVE_SNAPSHOT_SCHEMA:
        raise ValueError("Unsupported PocketCHIRP LiveRadio snapshot schema")
    if obj.get("kind") != "pocketchirp-live-radio-snapshot":
        raise ValueError("Invalid PocketCHIRP LiveRadio snapshot kind")
    return obj


def _live_snapshot_encode(snapshot):
    return _LIVE_SNAPSHOT_MAGIC + _json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _store_live_snapshot_as_working(snapshot):
    global _last_image_bytes, _last_raw_bytes, _last_hash_info
    data = _live_snapshot_encode(snapshot)
    _last_image_bytes = data
    _last_raw_bytes = data
    raw_sha = hashlib.sha256(data).hexdigest()
    _last_hash_info = (
        f"Live snapshot bytes: {len(data)}\n"
        f"Live snapshot SHA-256: {raw_sha}\n"
        "Format: PocketCHIRP detached LiveRadio snapshot"
    )


def _live_snapshot_driver_metadata(snapshot):
    driver = dict((snapshot or {}).get("driver") or {})
    return {
        "vendor": str(driver.get("vendor") or ""),
        "model": str(driver.get("model") or ""),
        "variant": str(driver.get("variant") or ""),
        "rclass": str(driver.get("rclass") or ""),
        "chirp_version": str(driver.get("chirpVersion") or ""),
        "pocketchirp_version": POCKETCHIRP_APP_VERSION,
        "pocketchirp_radio_key": str(driver.get("radioKey") or ""),
        "pocketchirp_vendor": str(driver.get("vendor") or ""),
        "pocketchirp_model": str(driver.get("model") or ""),
        "pocketchirp_variant": str(driver.get("variant") or ""),
        "pocketchirp_live_snapshot": "1",
    }


def _live_snapshot_validator(view_index):
    """Best-effort offline instance of the exact CHIRP driver for validation."""
    try:
        cls = _selected_class()
        root = cls(None)
        rf = root.get_features()
        if bool(getattr(rf, "has_sub_devices", False)):
            children = list(root.get_sub_devices() or [])
            if 0 <= int(view_index) < len(children):
                return children[int(view_index)]
        return root
    except Exception:
        return None


class _PocketChirpLiveSnapshotRadio:
    """Detached CHIRP-like radio backed only by PocketCHIRP snapshot JSON."""
    _POCKETCHIRP_LIVE_SNAPSHOT_PROXY = True

    def __init__(self, snapshot, view_index=None):
        self._snapshot = snapshot
        self._view_index = view_index
        driver = dict(snapshot.get("driver") or {})
        self.VENDOR = str(driver.get("vendor") or "")
        self.MODEL = str(driver.get("model") or "")
        self.VARIANT = str(driver.get("variant") or "")
        self.pipe = None
        self._metadata = _live_snapshot_driver_metadata(snapshot)
        if view_index is not None:
            try:
                self.VARIANT = str(snapshot["views"][int(view_index)].get("variant") or self.VARIANT)
            except Exception:
                pass

    def _view(self):
        views = list(self._snapshot.get("views") or [])
        if self._view_index is None:
            if len(views) == 1:
                return views[0]
            raise ValueError("Live snapshot root has sub-devices; choose a child view")
        if int(self._view_index) < 0 or int(self._view_index) >= len(views):
            raise ValueError("Live snapshot references an unknown sub-device")
        return views[int(self._view_index)]

    def get_features(self):
        if self._view_index is None and len(self._snapshot.get("views") or []) > 1:
            rec = dict(self._snapshot.get("rootFeatures") or {})
            rec["has_sub_devices"] = True
            rec["has_settings"] = False
            rec["has_bank"] = False
            return _live_features_from_record(rec)
        return _live_features_from_record(self._view().get("features") or {})

    def get_sub_devices(self):
        views = list(self._snapshot.get("views") or [])
        if len(views) <= 1:
            return []
        return [_PocketChirpLiveSnapshotRadio(self._snapshot, i) for i in range(len(views))]

    def get_memory(self, number):
        view = self._view()
        token = _live_memory_token(number)
        record = (view.get("records") or {}).get(token)
        rf = self.get_features()
        if record is None:
            from chirp import chirp_common
            mem = chirp_common.Memory()
            if isinstance(number, str):
                mem.extd_number = number
            else:
                mem.number = int(number)
            mem.empty = True
            return mem
        return _live_memory_from_record(record, rf)

    def set_memory(self, mem):
        view = self._view()
        extd = str(getattr(mem, "extd_number", "") or "")
        key = extd if extd else int(getattr(mem, "number", 0))
        view.setdefault("records", {})[_live_memory_token(key)] = _live_memory_record(mem, key)

    def erase_memory(self, number):
        from chirp import chirp_common
        mem = chirp_common.Memory()
        if isinstance(number, str):
            mem.extd_number = number
        else:
            mem.number = int(number)
        mem.empty = True
        self.set_memory(mem)

    def validate_memory(self, mem):
        validator = _live_snapshot_validator(0 if self._view_index is None else self._view_index)
        if validator is not None:
            try:
                return validator.validate_memory(mem)
            except Exception:
                pass
        try:
            from chirp import chirp_common
            return chirp_common.Radio.validate_memory(self, mem)
        except Exception:
            return []

    def check_set_memory_immutable_policy(self, old_mem, new_mem):
        # Keep exactly the immutable fields reported by the real driver at read.
        for field in list(getattr(old_mem, "immutable", []) or []):
            try:
                if getattr(old_mem, field) != getattr(new_mem, field):
                    raise ValueError("Memory field %s is immutable" % field)
            except AttributeError:
                continue
        return None

    def get_settings(self):
        return None


def _prepare_live_pipe(cls, java_transport):
    """Create CHIRP's serial-like LiveRadio pipe without consuming input."""
    pipe = _pipe_for_class(cls, java_transport)
    pipe.timeout = 0.25
    if hasattr(pipe, "write_timeout"):
        pipe.write_timeout = 1.5
    # Driver-declared serial attributes are transport configuration; all radio
    # commands and handshakes remain owned by the CHIRP LiveRadio driver.
    if not getattr(pipe, "is_ble", False):
        pipe.baudrate = int(getattr(cls, "BAUD_RATE", 9600) or 9600)
        _apply_driver_serial_open_contract(cls, pipe)
    return pipe


def _open_live_radio(cls, java_transport):
    from chirp import chirp_common
    if not issubclass(cls, chirp_common.LiveRadio):
        raise ValueError("Selected driver is not a CHIRP LiveRadio")
    pipe = _prepare_live_pipe(cls, java_transport)
    _note_exact_selected_driver(pipe, cls)
    radio = cls(pipe)
    _status_callback(radio, java_transport)
    sync_in = getattr(radio, "sync_in", None)
    if callable(sync_in):
        # Many LiveRadio classes connect in __init__ and expose no sync_in().
        # Drivers such as PMR-171 deliberately implement one; call it when the
        # selected driver provides it and let that driver own the handshake.
        sync_in()
    return radio, pipe


def _live_real_views(root_radio):
    """Return real driver views using PocketCHIRP's existing sub-device routing."""
    return _editor_radio_views(root_radio)


def _live_progress(java_transport, message, cur, maximum):
    try:
        java_transport.onChirpProgress(str(message), int(cur), int(maximum))
    except Exception:
        pass


def _build_live_snapshot(cls, java_transport):
    """Read a real LiveRadio into a detached snapshot without changing editor state."""
    radio, pipe = _open_live_radio(cls, java_transport)
    views = _live_real_views(radio)
    if not views:
        raise ValueError("LiveRadio driver exposed no editable memory view")

    counts = []
    for view, _dlo, _dhi, nlo, nhi, _variant in views:
        specials = [str(x) for x in _feature_seq(view.get_features(), "valid_special_chans")]
        counts.append(max(0, int(nhi) - int(nlo) + 1) + len(specials))
    total = max(1, sum(counts))
    done = 0
    out_views = []

    for view_index, (view, _dlo, _dhi, nlo, nhi, variant) in enumerate(views):
        rf = view.get_features()
        records = {}
        for native_n in range(int(nlo), int(nhi) + 1):
            _live_progress(java_transport, "Reading live memories", done, total)
            mem = view.get_memory(native_n)
            records[_live_memory_token(native_n)] = _live_memory_record(mem, native_n)
            done += 1
            _live_progress(java_transport, "Reading live memories", done, total)
        for special in [str(x) for x in _feature_seq(rf, "valid_special_chans")]:
            _live_progress(java_transport, "Reading live special memories", done, total)
            mem = view.get_memory(special)
            records[_live_memory_token(special)] = _live_memory_record(mem, special)
            done += 1
            _live_progress(java_transport, "Reading live special memories", done, total)

        out_views.append({
            "index": int(view_index),
            "variant": str(variant or getattr(view, "VARIANT", "") or ""),
            "features": _live_feature_record(rf),
            "records": records,
            "baseline": _json.loads(_json.dumps(records)),
        })

    driver = {
        "vendor": str(getattr(cls, "VENDOR", "") or ""),
        "model": str(getattr(cls, "MODEL", "") or ""),
        "variant": str(getattr(cls, "VARIANT", "") or ""),
        "rclass": str(getattr(cls, "__name__", "") or ""),
        "module": str(getattr(cls, "__module__", "") or ""),
        "radioKey": str(_selected_radio_key or ""),
        "chirpVersion": "",
    }
    try:
        import chirp
        driver["chirpVersion"] = str(getattr(chirp, "CHIRP_VERSION", "") or "")
    except Exception:
        pass

    snapshot = {
        "schema": _LIVE_SNAPSHOT_SCHEMA,
        "kind": "pocketchirp-live-radio-snapshot",
        "driver": driver,
        "rootFeatures": _live_feature_record(radio.get_features()),
        "views": out_views,
        "policy": {
            "offlineEdits": True,
            "changedMemoriesOnly": True,
            "readBackVerify": True,
            "settingsStaged": False,
        },
    }
    return snapshot


def _download_live_selected_editor(cls, java_transport):
    snapshot = _build_live_snapshot(cls, java_transport)
    _store_live_snapshot_as_working(snapshot)
    total = sum(len(v.get("records") or {}) for v in snapshot.get("views") or [])
    settings_note = ""
    if bool((snapshot.get("rootFeatures") or {}).get("live_original_has_settings", False)):
        settings_note = "\nLive radio-wide settings: intentionally not staged in this first safe adapter"
    return (
        "LIVE RADIO READ COMPLETE\n"
        f"Driver: {snapshot['driver']['vendor']} {snapshot['driver']['model']}"
        + (f" {snapshot['driver']['variant']}" if snapshot['driver']['variant'] else "")
        + f"\nDetached memories: {total}"
        + f"\nSub-device views: {len(snapshot.get('views') or [])}"
        + settings_note
        + "\nEditing is OFFLINE; hardware writes occur only after Write to Radio.\n"
        + _last_hash_info
    )


def _live_snapshot_changed_entries(snapshot):
    changed = []
    for vi, view in enumerate(snapshot.get("views") or []):
        current = dict(view.get("records") or {})
        baseline = dict(view.get("baseline") or {})
        for token in sorted(set(current) | set(baseline)):
            before = baseline.get(token)
            after = current.get(token)
            if before != after:
                changed.append((vi, token, before, after))
    return changed


def _live_record_key(record, token):
    if record is not None:
        key = record.get("requestedKey")
        if isinstance(key, str):
            return key
        try:
            return int(key)
        except Exception:
            pass
    if str(token).startswith("s:"):
        return str(token)[2:]
    return int(str(token)[2:])


def _live_drop_driver_cache(view, key):
    """Force verification to re-read hardware rather than a LiveRadio cache."""
    try:
        cache = getattr(view, "_memcache", None)
        if isinstance(cache, dict):
            # Special-memory names are often remapped to hidden numeric cache
            # keys by the driver. Clearing the whole per-radio cache is the only
            # vendor-independent way to guarantee verification hits hardware.
            cache.clear()
    except Exception:
        pass


def _live_write_preflight_guard(snapshot, real_views, changed):
    """Validate every changed memory BEFORE the first physical write."""
    problems = []
    driver = dict(snapshot.get("driver") or {})
    is_pmr171 = (
        str(driver.get("model") or "").strip().casefold() == "pmr-171"
        and str(driver.get("rclass") or "") == "PMR171Radio"
    )

    for vi, token, before, after in changed:
        if vi < 0 or vi >= len(real_views):
            problems.append("LiveRadio sub-device layout changed since the snapshot was read")
            continue
        if after is None:
            problems.append("Live snapshot lost memory record %s" % token)
            continue
        if bool(after.get("extraUnsupported")) or bool((before or {}).get("extraUnsupported")):
            problems.append(
                "%s uses driver-specific per-memory settings that PocketCHIRP cannot "
                "yet serialize losslessly; write is blocked rather than dropping them" % token)
            continue
        unsupported = set(after.get("unsupportedAttrs") or []) | set((before or {}).get("unsupportedAttrs") or [])
        if unsupported:
            problems.append(
                "%s contains unsupported driver-specific fields (%s); write is blocked" %
                (token, ", ".join(sorted(unsupported))))
            continue

        real_view = real_views[vi][0]
        rf = real_view.get_features()
        mem = _live_memory_from_record(after, rf)
        key = _live_record_key(after, token)
        if not isinstance(key, str):
            mem.number = int(key)

        # Known PMR-171 driver limitation: its published set_memory() encodes
        # Tone as TX-only and TSQL as the same tone in both directions. Use the
        # driver's OWN read helper during preflight to detect a stored RX tone
        # that differs from TX. This is read-only, happens before the first
        # physical write, and duplicates no protocol in PocketCHIRP.
        if is_pmr171 and before is not None and not isinstance(key, str):
            raw_reader = getattr(real_view, "_read_memory_raw24", None)
            if callable(raw_reader):
                try:
                    raw24 = bytes(raw_reader(int(key)))
                    if len(raw24) >= 12:
                        tx_idx = int(raw24[10])
                        rx_idx = int(raw24[11])
                        if rx_idx != 0 and rx_idx != tx_idx:
                            problems.append(
                                "%s has different TX/RX CTCSS values, which this PMR-171 "
                                "driver cannot write losslessly" % token)
                            continue
                except Exception as exc:
                    problems.append(
                        "%s PMR-171 tone-safety read failed before write: %s" %
                        (token, exc))
                    continue
            else:
                # Fail closed only when the snapshot itself clearly proves an
                # asymmetric tone and the exact driver's safe raw reader is not
                # available.
                bvals = dict(before.get("values") or {})
                if str(bvals.get("tmode") or "") == "Tone":
                    rt = float(bvals.get("rtone") or 0.0)
                    ct = float(bvals.get("ctone") or 0.0)
                    if ct > 0.0 and abs(ct - 88.5) > 0.05 and abs(ct - rt) > 0.05:
                        problems.append(
                            "%s has different TX/RX CTCSS values, which this PMR-171 "
                            "driver cannot write losslessly" % token)
                        continue

        if not bool(getattr(mem, "empty", False)):
            try:
                driver_problems = list(real_view.validate_memory(mem) or [])
            except Exception as exc:
                problems.append("%s driver validation failed: %s" % (token, exc))
                continue
            for problem in driver_problems:
                if problem.__class__.__name__ == "ValidationError":
                    problems.append("%s: %s" % (token, problem))

        if before is not None:
            try:
                old = _live_memory_from_record(before, rf)
                checker = getattr(real_view, "check_set_memory_immutable_policy", None)
                if callable(checker):
                    checker(old, mem)
            except Exception as exc:
                problems.append("%s immutable-field check failed: %s" % (token, exc))

    if problems:
        shown = problems[:20]
        suffix = "; plus %d more" % (len(problems) - len(shown)) if len(problems) > len(shown) else ""
        raise ValueError("LIVE RADIO WRITE BLOCKED: " + "; ".join(shown) + suffix)


def _live_compare_records(expected, actual):
    """Compare editor-visible fields while tolerating driver default bookkeeping."""
    ev = dict((expected or {}).get("values") or {})
    av = dict((actual or {}).get("values") or {})
    fields = (
        "empty", "name", "freq", "duplex", "offset", "tmode", "rtone", "ctone",
        "dtcs", "rx_dtcs", "dtcs_polarity", "cross_mode", "mode", "skip",
        "tuning_step", "comment", "tx_freq", "dv_urcall", "dv_rpt1call",
        "dv_rpt2call", "dv_code", "power",
    )
    mismatches = []
    for field in fields:
        if field not in ev:
            continue
        a = av.get(field)
        e = ev.get(field)
        if field in ("rtone", "ctone", "tuning_step"):
            try:
                if abs(float(a or 0.0) - float(e or 0.0)) <= 0.051:
                    continue
            except Exception:
                pass
        if a != e:
            mismatches.append("%s expected=%r read=%r" % (field, e, a))
    return mismatches


def _controlled_write_live_snapshot(java_transport, image_bytes):
    from chirp import chirp_common
    snapshot = _live_snapshot_decode(image_bytes)
    cls = _selected_class()
    if not issubclass(cls, chirp_common.LiveRadio):
        raise ValueError("Live snapshot selected, but target driver is not a CHIRP LiveRadio")

    snap_ident = _live_snapshot_driver_metadata(snapshot)
    selected = _selected_identity()
    if not _canonical_identity_match(_metadata_identity(snap_ident), selected):
        raise ValueError("LIVE SNAPSHOT / RADIO MISMATCH — write blocked")

    changed = _live_snapshot_changed_entries(snapshot)
    if not changed:
        _store_live_snapshot_as_working(snapshot)
        return (
            "LIVE RADIO WRITE COMPLETE\n"
            f"Radio: {snapshot['driver']['vendor']} {snapshot['driver']['model']}\n"
            "Changed memories: 0\nNothing needed to be written."
        )

    live_root, pipe = _open_live_radio(cls, java_transport)
    real_views = _live_real_views(live_root)
    if len(real_views) != len(snapshot.get("views") or []):
        raise ValueError(
            "LiveRadio sub-device layout differs from the downloaded snapshot; write blocked")

    # Validate ALL changes before the first set_memory()/erase_memory() call so a
    # late unsupported field cannot leave a partially written radio.
    _live_write_preflight_guard(snapshot, real_views, changed)

    total = len(changed)
    verified = 0
    try:
        for index, (vi, token, before, after) in enumerate(changed, 1):
            real_view = real_views[vi][0]
            rf = real_view.get_features()
            key = _live_record_key(after, token)
            mem = _live_memory_from_record(after, rf)
            if not isinstance(key, str):
                mem.number = int(key)

            _live_progress(java_transport, "Writing changed live memories", index - 1, total)
            if bool(getattr(mem, "empty", False)):
                erase = getattr(real_view, "erase_memory", None)
                if callable(erase):
                    erase(key)
                else:
                    real_view.set_memory(mem)
            else:
                real_view.set_memory(mem)

            # Per-memory verification must bypass common Kenwood-style caches.
            _live_drop_driver_cache(real_view, key)
            actual_mem = real_view.get_memory(key)
            actual = _live_memory_record(actual_mem, key)
            mismatches = _live_compare_records(after, actual)
            if mismatches:
                # The physical radio now contains `actual`. Record that as the
                # new baseline while keeping the user's desired current record,
                # so a retry remains a real diff instead of rewriting verified
                # channels or pretending the mismatch succeeded.
                snapshot["views"][vi].setdefault("baseline", {})[token] = actual
                _store_live_snapshot_as_working(snapshot)
                raise ValueError(
                    "LIVE RADIO READ-BACK MISMATCH %s: %s" %
                    (token, "; ".join(mismatches[:8])))

            # Verified write becomes the new hardware baseline. Use the actual
            # driver-normalized memory for both current and baseline so benign
            # normalization does not leave a false dirty diff.
            snapshot["views"][vi].setdefault("records", {})[token] = actual
            snapshot["views"][vi].setdefault("baseline", {})[token] = _json.loads(_json.dumps(actual))
            verified += 1
            _live_progress(java_transport, "Verifying changed live memories", index, total)
    except Exception:
        # Preserve any already-verified baseline advances. A retry will only
        # attempt the still-different memories, preventing duplicate live writes.
        _store_live_snapshot_as_working(snapshot)
        raise

    _store_live_snapshot_as_working(snapshot)
    # Undo snapshots captured before a physical commit contain the old hardware
    # baseline. Clear them so Undo can never make PocketCHIRP believe an old
    # baseline still represents the radio after a successful live write.
    return (
        "LIVE RADIO WRITE COMPLETE\n"
        f"Radio: {snapshot['driver']['vendor']} {snapshot['driver']['model']}"
        + (f" {snapshot['driver']['variant']}" if snapshot['driver'].get('variant') else "")
        + f"\nChanged memories: {total}"
        + f"\nRead-back verified: {verified}/{total}"
        + "\nWrite policy: changed memories only"
    )

def download_selected_editor(java_transport, physical_transport_kind="unknown"):
    from chirp import chirp_common
    cls = _selected_class()
    if issubclass(cls, chirp_common.LiveRadio):
        return _download_live_selected_editor(cls, java_transport)
    if not issubclass(cls, chirp_common.CloneModeRadio):
        raise ValueError(f"{cls.VENDOR} {cls.MODEL} is not a clone-mode radio")

    pipe = _prepare_clone_pipe(cls, java_transport)

    radio = _sync_in_once(
        cls, pipe, java_transport, physical_transport_kind)
    _store_downloaded_radio(radio)

    rf = radio.get_features()
    low, high = rf.memory_bounds
    return (
        "RADIO READ COMPLETE\n"
        f"Driver: {radio.VENDOR} {radio.MODEL}"
        + (f" {radio.VARIANT}" if getattr(radio, "VARIANT", "") else "")
        + f"\nMemory range: {low}-{high}\n"
        + _last_hash_info
    )


def _metadata_for_image(data):
    from chirp import chirp_common
    if _is_live_snapshot_bytes(data):
        snapshot = _live_snapshot_decode(data)
        return bytes(data), _live_snapshot_driver_metadata(snapshot)
    try:
        raw, metadata = chirp_common.CloneModeRadio._strip_metadata(data)
        return raw, metadata or {}
    except Exception:
        return _split_chirp_img(data)[0], {}


def _entry_for_metadata(metadata):
    """Map standard CHIRP image metadata to a visible PocketCHIRP catalog row."""
    _ensure_radio_catalog()
    vendor = metadata.get("vendor")
    model = metadata.get("model")
    variant = metadata.get("variant") or ""
    if not vendor or not model:
        return None

    wanted = _fold_radio_identity((vendor, model, variant))
    for e in _radio_catalog_cache.get("radios", []):
        if _fold_radio_identity(_custom_public_identity(e)) == wanted:
            return e
    if not variant:
        wanted_vm = tuple(str(x or "").strip().casefold() for x in (vendor, model))
        for e in _radio_catalog_cache.get("radios", []):
            actual_vm = tuple(str(x or "").strip().casefold() for x in (
                e.get("vendor", ""), e.get("model", "")))
            if actual_vm == wanted_vm:
                return e
    return None


def _chirp_radio_from_image_bytes(data):
    """Open image bytes using CHIRP's own image-class detection machinery.

    Image operations must not depend on PocketCHIRP having requested the radio
    catalog first.  Initializing the engine catalog registers CHIRP's bundled
    drivers through directory.import_drivers(), so get_radio_by_image() works
    correctly even when an Open Image request races the app's async catalog load.
    """
    _ensure_radio_catalog()
    from chirp import directory

    raw = bytes(data or b"")
    if not raw:
        raise ValueError("No radio image bytes were supplied")

    # model_alias_map.yaml identities are marketed names, not registered CHIRP
    # classes. PocketCHIRP intentionally preserves those names in image metadata
    # (for example Baofeng AR-5RM), so resolve a known map alias to its exact
    # executable class before asking CHIRP's generic detector to match the model
    # string. This restores older PocketCHIRP alias-stamped saves without
    # modifying their bytes or weakening normal image validation.
    try:
        _, _metadata = _metadata_for_image(raw)
        _mapped_entry = _entry_for_metadata(_metadata or {})
        if _mapped_entry is not None and _mapped_entry.get("kind") == "map-alias":
            return _radio_from_exact_class_image_bytes(
                _find_loaded_radio_class(_mapped_entry), raw)
    except Exception:
        # Fall through to CHIRP's normal detector. If the image is genuinely
        # invalid it will raise the original authoritative error below.
        pass

    name = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tmp:
            name = tmp.name
            tmp.write(raw)
        return directory.get_radio_by_image(name)
    finally:
        if name:
            try:
                os.unlink(name)
            except OSError:
                pass


def _entry_for_radio_runtime(radio, metadata=None):
    """Return the visible chooser entry for a CHIRP runtime image class.

    Detected-only subclasses deliberately have no chooser row. Map those back
    to CHIRP's _DETECTED_BY manager while retaining the exact runtime class in
    the image itself. Marketed aliases still map by their image metadata first.
    """
    _ensure_radio_catalog()

    if metadata:
        direct = _entry_for_metadata(metadata)
        if direct is not None:
            return direct

    runtime_cls = _unwrap_runtime_class(radio.__class__)
    visible_cls = _detected_manager_class(runtime_cls) or runtime_cls

    candidates = []
    visible_identity = _fold_radio_identity(_custom_public_identity(visible_cls))
    for e in _radio_catalog_cache.get("radios", []):
        try:
            entry_cls = _unwrap_runtime_class(_find_loaded_radio_class(e))
        except Exception:
            continue

        score = None
        if (e.get("kind") == "driver" and entry_cls is visible_cls and
                _fold_radio_identity(_custom_public_identity(e)) == visible_identity):
            score = 0
        elif (entry_cls is visible_cls and
              _fold_radio_identity(_custom_public_identity(e)) == visible_identity):
            score = 1
        elif entry_cls is visible_cls:
            score = 2
        if score is not None:
            candidates.append((score, str(e.get("key") or ""), e))

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]
    return None


def _runtime_image_identity(radio, metadata=None):
    impl = _unwrap_runtime_class(radio.__class__)
    manager = _detected_manager_class(impl)
    visible_entry = _entry_for_radio_runtime(radio, metadata)
    return {
        "vendor": str(getattr(radio, "VENDOR", "") or ""),
        "model": str(getattr(radio, "MODEL", "") or ""),
        "variant": str(getattr(radio, "VARIANT", "") or ""),
        "rclass": str(getattr(impl, "__name__", "") or ""),
        "module": str(getattr(impl, "__module__", "") or ""),
        "detectedOnly": bool(manager is not None),
        "detectedByClass": str(getattr(manager, "__name__", "") or "") if manager else "",
        "radioKey": str(visible_entry.get("key") or "") if visible_entry else "",
        "visibleVendor": str(visible_entry.get("vendor") or "") if visible_entry else "",
        "visibleModel": str(visible_entry.get("model") or "") if visible_entry else "",
        "visibleVariant": str(visible_entry.get("variant") or "") if visible_entry else "",
    }


def _entry_class_identity(entry):
    """Return canonical CHIRP driver identity for one radio catalog entry."""
    if not entry:
        return None
    try:
        cls = _find_loaded_radio_class(entry)
        return {
            "vendor": str(getattr(cls, "VENDOR", "") or ""),
            "model": str(getattr(cls, "MODEL", "") or ""),
            "variant": str(getattr(cls, "VARIANT", "") or ""),
            "rclass": cls.__name__,
            "module": str(entry.get("module") or ""),
            "key": str(entry.get("key") or ""),
            "displayVendor": str(entry.get("vendor") or ""),
            "displayModel": str(entry.get("model") or ""),
            "displayVariant": str(entry.get("variant") or ""),
        }
    except Exception:
        return None


def _selected_identity():
    if not _selected_radio_key or not _radio_catalog_by_key:
        return None
    return _entry_class_identity(_radio_catalog_by_key.get(_selected_radio_key))


def _entries_share_backend_driver(first, second):
    """True only when two catalog identities execute the exact same backend class.

    This is intentionally stricter than inheritance/duck-typing. It exists for
    CHIRP marketed aliases (for example Baofeng 5RM and AR-5RM) and equivalent
    custom aliases which are merely alternate labels for one implementation.
    """
    if not first or not second:
        return False
    try:
        first_cls = _unwrap_runtime_class(_find_loaded_radio_class(first))
        second_cls = _unwrap_runtime_class(_find_loaded_radio_class(second))
        return first_cls is second_cls
    except Exception:
        return False


def _metadata_identity(metadata):
    if not metadata:
        return None
    return {
        "vendor": str(metadata.get("vendor") or ""),
        "model": str(metadata.get("model") or ""),
        "variant": str(metadata.get("variant") or ""),
        "rclass": str(metadata.get("rclass") or ""),
        "chirpVersion": str(metadata.get("chirp_version") or ""),
    }


def identify_image_bytes_json(data):
    """Identify image bytes using the same CHIRP image loader as desktop CHIRP."""
    data = bytes(data or b"")
    if not data:
        return _json.dumps({
            "vendor": "", "model": "", "variant": "", "rclass": "",
            "radioKey": "", "source": "empty", "confidence": "none",
        }, separators=(",", ":"))

    raw, metadata = _metadata_for_image(data)
    if _is_live_snapshot_bytes(data):
        ident = _metadata_identity(metadata) or {}
        entry = _entry_for_metadata(metadata or {})
        ident.update({
            "radioKey": str(entry.get("key") or "") if entry else "",
            "source": "live-snapshot-metadata",
            "confidence": "authoritative",
            "metadataPresent": True,
            "rawBytes": len(raw),
        })
        return _json.dumps(ident, separators=(",", ":"))

    try:
        radio = _chirp_radio_from_image_bytes(data)
    except Exception as exc:
        return _json.dumps({
            "vendor": "", "model": "", "variant": "", "rclass": "",
            "radioKey": "", "source": "unknown", "confidence": "none",
            "metadataPresent": bool(metadata), "rawBytes": len(raw),
            "error": "%s: %s" % (exc.__class__.__name__, exc),
        }, separators=(",", ":"))

    ident = _runtime_image_identity(radio, metadata)
    ident.update({
        "source": "chirp-get-radio-by-image",
        "confidence": "authoritative" if metadata else "chirp-detected",
        "metadataPresent": bool(metadata),
        "rawBytes": len(raw),
    })
    return _json.dumps(ident, separators=(",", ":"))





def _canonical_identity_match(a, b):
    if not a or not b:
        return False
    if _fold_radio_identity((
            a.get("vendor", ""), a.get("model", ""), a.get("variant", ""))) != _fold_radio_identity((
            b.get("vendor", ""), b.get("model", ""), b.get("variant", ""))):
        return False
    if a.get("rclass") and b.get("rclass"):
        return a.get("rclass") == b.get("rclass")
    return True


def _candidate_match_entries(raw):
    """Best-effort identification of legacy/raw images via CHIRP match_model()."""
    if _radio_catalog_cache is None:
        return []

    matches = []
    seen_classes = set()
    for entry in _radio_catalog_cache.get("radios", []):
        try:
            cls = _find_loaded_radio_class(entry)
            ident = (
                cls.__module__,
                cls.__name__,
                str(getattr(cls, "VENDOR", "") or ""),
                str(getattr(cls, "MODEL", "") or ""),
                str(getattr(cls, "VARIANT", "") or ""),
            )
            if ident in seen_classes:
                continue
            seen_classes.add(ident)

            matcher = getattr(cls, "match_model", None)
            if not callable(matcher):
                continue
            try:
                ok = bool(matcher(raw, "candidate.img"))
            except TypeError:
                ok = bool(matcher(raw))
            if ok:
                matches.append({
                    "vendor": ident[2],
                    "model": ident[3],
                    "variant": ident[4],
                    "rclass": ident[1],
                    "module": str(entry.get("module") or ""),
                    "key": str(entry.get("key") or ""),
                })
        except Exception:
            continue
    return matches


def image_compatibility_bytes_json(data):
    """Compare CHIRP's actual image runtime class with the selected target."""
    data = bytes(data or b"")
    if not data:
        return _json.dumps({
            "level": "none",
            "writeAllowed": False,
            "requiresExtraConfirmation": True,
            "reason": "empty-image",
        }, separators=(",", ":"))

    _ensure_radio_catalog()
    raw, metadata = _metadata_for_image(data)
    selected_entry = _entry() if _selected_radio_key else None
    selected = _selected_identity()

    result = {
        "rawBytes": len(raw),
        "rawSha256": hashlib.sha256(raw).hexdigest(),
        "metadataPresent": bool(metadata),
        "selected": selected,
        "level": "unknown",
        "reason": "unidentified-image",
        "writeAllowed": False,
        "requiresExtraConfirmation": True,
    }

    if selected_entry is None:
        result.update({"level": "no_target", "reason": "no-selected-target"})
        return _json.dumps(result, separators=(",", ":"))

    if _is_live_snapshot_bytes(data):
        image_entry = _entry_for_metadata(metadata or {})
        result["image"] = _metadata_identity(metadata)
        if image_entry and image_entry.get("key") == selected_entry.get("key"):
            result.update({
                "level": "exact", "reason": "live-snapshot-target-match",
                "writeAllowed": True, "requiresExtraConfirmation": False,
            })
        elif image_entry and _entries_share_backend_driver(image_entry, selected_entry):
            result.update({
                "level": "compatible",
                "reason": "live-snapshot-same-backend-driver",
                "writeAllowed": True,
                "requiresExtraConfirmation": True,
            })
        else:
            result.update({"level": "mismatch", "reason": "live-snapshot-target-mismatch"})
        return _json.dumps(result, separators=(",", ":"))

    # Use the same custom-aware image ownership path used by editor projection
    # and the actual upload. Runtime custom drivers are intentionally not left in
    # CHIRP's global directory, so bundled-only detection can misidentify a valid
    # custom image (for example UV-K5 VUURWERK) and incorrectly block writing.
    custom_entry = _custom_entry_for_image_metadata(metadata)
    try:
        radio = _radio_from_image_bytes(data)
    except Exception as exc:
        result["error"] = "%s: %s" % (exc.__class__.__name__, exc)
        result["reason"] = "chirp-image-detection-failed"
        return _json.dumps(result, separators=(",", ":"))

    image_identity = _runtime_image_identity(radio, metadata)
    if custom_entry is not None:
        # Preserve the exact runtime custom entry in the safety report instead of
        # allowing a same-identity bundled class to win catalog ordering.
        image_identity.update({
            "radioKey": str(custom_entry.get("key") or ""),
            "visibleVendor": str(custom_entry.get("vendor") or ""),
            "visibleModel": str(custom_entry.get("model") or ""),
            "visibleVariant": str(custom_entry.get("variant") or ""),
            "customDriver": True,
        })
    result["image"] = image_identity
    image_entry = custom_entry if custom_entry is not None else _entry_for_radio_runtime(radio, metadata)
    selected_cls = _unwrap_runtime_class(_selected_class())
    image_cls = _unwrap_runtime_class(radio.__class__)
    image_manager = _detected_manager_class(image_cls)

    if image_entry and image_entry.get("key") == selected_entry.get("key"):
        result.update({
            "level": "exact",
            "reason": "detected-subclass-target-match" if image_manager else "chirp-image-target-match",
            "writeAllowed": True,
            "requiresExtraConfirmation": False,
        })
    elif image_manager is selected_cls:
        # Fallback for a detected-only class if a future CHIRP manager is not
        # represented in the visible catalog exactly as expected.
        result.update({
            "level": "exact",
            "reason": "chirp-detected-manager-match",
            "writeAllowed": True,
            "requiresExtraConfirmation": False,
        })
    elif ((image_entry and _entries_share_backend_driver(image_entry, selected_entry))
          or image_cls is selected_cls):
        # A CHIRP marketed alias may carry different vendor/model metadata while
        # using the exact same parser/writer class.  Permit that relationship
        # instead of hard-blocking it, but keep the user's extra confirmation so
        # a sibling marketed label is visible before a destructive write.
        result.update({
            "level": "compatible",
            "reason": "chirp-same-backend-driver",
            "writeAllowed": True,
            "requiresExtraConfirmation": True,
        })
    else:
        result.update({
            "level": "mismatch",
            "reason": "chirp-image-target-mismatch",
            "writeAllowed": False,
            "requiresExtraConfirmation": True,
        })

    return _json.dumps(result, separators=(",", ":"))
def backup_connected_radio_once_bytes(java_transport):
    """Read connected radio and return a CHIRP .img backup without replacing work."""
    from chirp import chirp_common

    cls = _selected_class()
    if issubclass(cls, chirp_common.LiveRadio):
        # Preserve PocketCHIRP's existing automatic pre-write backup guarantee.
        # Build and return a detached snapshot WITHOUT replacing the user's
        # current working snapshot/image.
        snapshot = _build_live_snapshot(cls, java_transport)
        return _live_snapshot_encode(snapshot)
    if not issubclass(cls, chirp_common.CloneModeRadio):
        raise ValueError("Selected radio is not a clone-mode radio.")

    pipe = _prepare_clone_pipe(cls, java_transport)
    radio = _sync_in_once(cls, pipe, java_transport)

    name = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tmp:
            name = tmp.name
        radio.save(name)
        with open(name, "rb") as f:
            data = f.read()
        return data
    finally:
        if name:
            try:
                os.unlink(name)
            except OSError:
                pass






def _custom_entry_for_image_metadata(metadata):
    """Return the exact loaded custom-driver entry for image metadata, if any.

    New PocketCHIRP images carry exact custom-driver key/SHA/class metadata.
    That identity is authoritative for parser selection and survives Save ->
    close -> reopen. Legacy images retain the prior public-identity fallback.
    """
    if not metadata:
        return None

    exact_key = str(metadata.get("pocketchirp_custom_driver_key") or "").strip()
    if exact_key:
        entry = _custom_driver_entries.get(exact_key)
        if entry is None:
            raise ValueError(
                "This image requires a PocketCHIRP custom driver that is not loaded "
                f"({exact_key}). Reload the matching Python driver before opening or writing it."
            )

        expected_sha = str(metadata.get("pocketchirp_custom_driver_sha256") or "").strip().lower()
        actual_sha = str(entry.get("sha256") or "").strip().lower()
        if expected_sha and actual_sha and expected_sha != actual_sha:
            raise ValueError(
                "PocketCHIRP custom-driver metadata SHA-256 does not match the loaded driver."
            )

        expected_class = str(metadata.get("pocketchirp_custom_driver_class") or "").strip()
        actual_class = str(entry.get("class") or "").strip()
        if expected_class and actual_class and expected_class != actual_class:
            raise ValueError(
                "PocketCHIRP custom-driver metadata class does not match the loaded driver."
            )

        wanted = _fold_radio_identity((
            metadata.get("vendor"),
            metadata.get("model"),
            metadata.get("variant") or "",
        ))
        actual_identity = _fold_radio_identity(_custom_public_identity(entry))
        if wanted and wanted[0] and wanted[1] and actual_identity != wanted:
            raise ValueError(
                "PocketCHIRP custom-driver metadata identity does not match the loaded driver."
            )
        return entry

    # Migration for images created before exact custom provenance was embedded.
    wanted = _fold_radio_identity((
        metadata.get("vendor"),
        metadata.get("model"),
        metadata.get("variant") or "",
    ))
    if not wanted or not wanted[0] or not wanted[1]:
        return None

    selected = _radio_catalog_by_key.get(_selected_radio_key) if _selected_radio_key else None
    if (selected and (selected.get("customDriver") or selected.get("kind") == "custom")
            and _fold_radio_identity(_custom_public_identity(selected)) == wanted):
        return selected

    matches = [
        entry for entry in (_radio_catalog_cache or {}).get("radios", [])
        if (entry.get("customDriver") or entry.get("kind") == "custom")
        and _fold_radio_identity(_custom_public_identity(entry)) == wanted
    ]
    return matches[0] if len(matches) == 1 else None

def _radio_from_exact_class_image_bytes(cls, data):
    """Instantiate one already-resolved CHIRP class from saved image bytes."""
    name = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tmp:
            name = tmp.name
            tmp.write(bytes(data or b""))
        return cls(name)
    finally:
        if name:
            try:
                os.unlink(name)
            except OSError:
                pass


def _radio_from_image_bytes(image_bytes=None):
    data = _last_image_bytes if image_bytes is None else image_bytes
    if not data:
        raise ValueError("No working radio image is loaded")

    if _is_live_snapshot_bytes(data):
        return _PocketChirpLiveSnapshotRadio(_live_snapshot_decode(data))

    # Custom drivers are intentionally NOT left in CHIRP's global directory
    # registry.  Reopen a custom image with the exact registered custom class
    # before falling back to CHIRP's normal image detector.  This is critical for
    # post-read editor projection: the physical clone may succeed while the
    # bundled detector chooses a different/base class and yields empty or wrong
    # memories (for example UV-K5 VUURWERK).
    _, metadata = _metadata_for_image(data)
    custom_entry = _custom_entry_for_image_metadata(metadata)
    if custom_entry is not None:
        return _radio_from_exact_class_image_bytes(
            _find_loaded_radio_class(custom_entry), data)

    # Bundled drivers retain the newer CHIRP-native ownership/detection path,
    # preserving aliases, MODEL_COMPAT, match_model(), and detected-only classes.
    return _chirp_radio_from_image_bytes(data)


def load_editor_image_bytes(data):
    global _selected_radio_key, _selected_radio_class

    data = bytes(data or b"")
    if not data:
        raise ValueError("No radio image bytes were supplied")

    if _is_live_snapshot_bytes(data):
        _, metadata = _metadata_for_image(data)
        entry = _entry_for_metadata(metadata)
        radio = _PocketChirpLiveSnapshotRadio(_live_snapshot_decode(data))
    else:
        _, metadata = _metadata_for_image(data)
        custom_entry = _custom_entry_for_image_metadata(metadata)
        if custom_entry is not None:
            radio = _radio_from_exact_class_image_bytes(
                _find_loaded_radio_class(custom_entry), data)
            entry = custom_entry
        else:
            radio = _chirp_radio_from_image_bytes(data)
            entry = _entry_for_radio_runtime(radio, metadata)

    # Keep the chooser on CHIRP's visible manager/marketed alias. For custom
    # images, preserve the exact loaded custom entry selected above.
    if entry is not None:
        _selected_radio_key = entry["key"]
        _selected_radio_class = _find_loaded_radio_class(entry)

    _save_working_radio(radio)
    return pocketchirp_radio_document_json()




# =============================================================================
# POCKETCHIRP 2.0 LOCAL-EDIT MATERIALIZER
# =============================================================================
# Ordinary edits now remain in the proprietary PocketCHIRP application as a
# neutral operation journal.  The separate GPL Engine sees those edits only
# when PocketCHIRP needs a concrete CHIRP .img (Save / Write / an explicitly
# driver-specific operation).
#
# REGRESSION GUARD:
# - This function operates only on an in-memory image and edit journal.
# - It never opens BLE/USB and never changes clone timing, MTU, baud, resolver,
#   radio prompts, or any transport policy.
# - The Engine's previous working image/selection is restored before return,
#   even when a driver rejects an edit.
# - Only the explicitly-listed editor mutation entry points may be replayed.
# =============================================================================
def materialize_editor_edits_bytes(base_image_bytes, edit_bundle_bytes):
    global _last_image_bytes, _last_raw_bytes, _last_hash_info
    global _selected_radio_key, _selected_radio_class

    base = bytes(base_image_bytes or b"")
    if not base:
        raise ValueError("No base radio image was supplied for edit materialization.")

    bundle_raw = bytes(edit_bundle_bytes or b"")
    if not bundle_raw:
        bundle = {"schemaVersion": 1, "operations": []}
    else:
        bundle = _json.loads(bundle_raw.decode("utf-8-sig"))
    if not isinstance(bundle, dict):
        raise ValueError("PocketCHIRP edit bundle must be a JSON object.")
    if int(bundle.get("schemaVersion", 1) or 1) != 1:
        raise ValueError("Unsupported PocketCHIRP edit-bundle schema version.")

    operations = bundle.get("operations") or []
    if not isinstance(operations, list):
        raise ValueError("PocketCHIRP edit-bundle operations must be an array.")

    old_image = _last_image_bytes
    old_raw = _last_raw_bytes
    old_hash_info = _last_hash_info
    old_key = _selected_radio_key
    old_class = _selected_radio_class

    try:
        raw, metadata = _metadata_for_image(base)
        expected_hash = str(bundle.get("baseRawSha256") or "").strip().lower()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if expected_hash and expected_hash != actual_hash:
            raise ValueError(
                "PocketCHIRP edit bundle does not match its base image "
                f"(expected {expected_hash}, got {actual_hash}).")

        # Resolve exactly as the normal explicit .img loader does, but do not
        # build/return the large Radio Document here. That document belongs on
        # the streamed read/load boundary, not inside Save/Write materialization.
        expected_key = str(bundle.get("selectedRadioKey") or "").strip()
        # The selected WRITE TARGET and the image's parser identity are separate.
        # Do not reject a compatible cross-model/variant workflow merely because
        # the base .img metadata names its originating model. We only verify that
        # the app and Engine still agree on the selected target before temporarily
        # switching to the base image's parser class for edit replay.
        if expected_key and old_key and expected_key != old_key:
            raise ValueError(
                "PocketCHIRP and CHIRP Engine disagree about the selected target radio.")

        # CHIRP's image loader determines the parser/runtime class. The
        # proprietary app's selected write target remains untouched.
        radio = _radio_from_image_bytes(base)
        _save_working_radio(radio)

        allowed = {
            "update_memory_json": update_memory_json,
            "delete_memories_json": delete_memories_json,
            "update_setting_json": update_setting_json,
            "rearrange_memories_json": rearrange_memories_json,
            "set_bank_json": set_bank_json,
        }

        index = 0
        while index < len(operations):
            item = operations[index]
            if not isinstance(item, dict):
                raise ValueError(f"Edit operation {index + 1} is not a JSON object.")
            name = str(item.get("operation") or "")

            if name == "update_setting_json":
                # PocketCHIRP's UI may journal several setting controls as separate
                # operations. Desktop CHIRP does not call set_settings() once per
                # control: it mutates one RadioSettings tree and commits it once.
                # Coalesce each contiguous settings run to the FINAL requested value
                # for each stable setting identity, then make one driver call.
                final_changes = {}
                while index < len(operations):
                    candidate = operations[index]
                    if not isinstance(candidate, dict) or str(candidate.get("operation") or "") != "update_setting_json":
                        break
                    args = candidate.get("args") or []
                    if not isinstance(args, list) or len(args) != 1:
                        raise ValueError("Edit operation arguments must contain one settings JSON payload: update_setting_json")
                    for change in _setting_changes_from_json(args[0]):
                        target_name = str(change.get("name", ""))
                        target_id = str(change.get("id", "") or "")
                        if not target_name:
                            raise ValueError("Radio setting name is missing")
                        key = target_id or ("name:" + target_name)
                        # Reinsert so the final occurrence also determines ordering.
                        if key in final_changes:
                            del final_changes[key]
                        final_changes[key] = dict(change)
                    index += 1
                _apply_setting_changes_json(
                    _json.dumps({"changes": list(final_changes.values())}, separators=(",", ":")),
                    return_document=False)
                continue

            fn = allowed.get(name)
            if fn is None:
                raise ValueError("Unsupported PocketCHIRP edit operation: " + name)
            args = item.get("args") or []
            if not isinstance(args, list):
                raise ValueError("Edit operation arguments must be an array: " + name)
            fn(*args)
            index += 1

        # Copy before restoring the Engine's pre-existing working state.
        result = bytes(_last_image_bytes or b"")
        if not result:
            raise ValueError("CHIRP edit materialization produced an empty image")
        return result
    finally:
        _last_image_bytes = old_image
        _last_raw_bytes = old_raw
        _last_hash_info = old_hash_info
        _selected_radio_key = old_key
        _selected_radio_class = old_class


def materialize_editor_edits_b64(base_image_bytes, edit_bundle_bytes):
    """String fallback for the Android/Chaquopy bytes conversion boundary.

    The normal AIDL path returns raw bytes through a ParcelFileDescriptor.  This
    fallback is used only if Chaquopy unexpectedly converts a non-empty Python
    bytes result to a null/empty Java byte array.
    """
    result = materialize_editor_edits_bytes(base_image_bytes, edit_bundle_bytes)
    if not result:
        raise ValueError("CHIRP edit materialization produced an empty image")
    return base64.b64encode(result).decode("ascii")


def materialize_editor_edits_b64_json(base_image_b64, edit_bundle_json):
    """Neutral JSON/stream RPC wrapper for edit materialization.

    The app sends the base .img as base64 plus the edit bundle as UTF-8 JSON
    through requestJsonStream(). This deliberately bypasses the dedicated
    materializeEditorEdits AIDL transaction while preserving the same Python
    materializer and validation logic.
    """
    encoded = str(base_image_b64 or "").strip()
    if not encoded:
        raise ValueError("No base radio image was supplied for edit materialization.")
    try:
        base = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("Base radio image is not valid base64") from exc
    edits = str(edit_bundle_json or "").encode("utf-8")
    return materialize_editor_edits_b64(base, edits)


def validate_current_image_bytes(data):
    data = bytes(data or b"")
    raw, _ = _metadata_for_image(data)
    report = _json.loads(image_compatibility_bytes_json(data))
    selected = report.get("selected") or {}

    return _json.dumps({
        "identity": report,
        "rawBytes": len(raw),
        "rawSha256": hashlib.sha256(raw).hexdigest(),
        "target": {
            "vendor": selected.get("vendor", ""),
            "model": selected.get("model", ""),
            "variant": selected.get("variant", ""),
            "rclass": selected.get("rclass", ""),
        },
    })




def controlled_write_current_once_bytes(java_transport, image_bytes, transport_context_json=None):
    """Write the current working image without forcing a full post-write reread."""
    image_bytes = bytes(image_bytes or b"")
    identity = _json.loads(image_compatibility_bytes_json(image_bytes))
    if not identity.get("writeAllowed"):
        raise ValueError(
            "Image/target CHIRP compatibility check failed: "
            + str(identity.get("reason") or identity.get("level") or "unknown")
        )

    if _is_live_snapshot_bytes(image_bytes):
        return _controlled_write_live_snapshot(java_transport, image_bytes)

    # The image's CHIRP runtime class owns upload. For detected-only subclasses
    # this is intentionally different from the visible chooser manager.
    radio = _radio_from_image_bytes(image_bytes)
    cls = radio.__class__
    raw_before, _ = _metadata_for_image(image_bytes)
    expected_hash = hashlib.sha256(raw_before).hexdigest()

    # Do not add a PocketCHIRP-wide memory-validation veto before sync_out().
    # Individual edits have already passed the driver's validate_memory(); the
    # CHIRP driver owns any whole-image/radio-specific upload restrictions.

    # Use the same neutral clone-session preparation as downloads and
    # write+verify. Driver-specific purge/handshake behavior remains owned by
    # the selected CHIRP runtime class rather than imposed globally here.
    pipe = _prepare_clone_pipe(cls, java_transport)
    _prepare_native_usb_class_adapter(cls, pipe)
    _enforce_ble_write_requirements(cls, pipe, radio, transport_context_json)
    radio.pipe = pipe
    _status_callback(radio, java_transport)
    radio.sync_out()

    return (
        "CONTROLLED WRITE COMPLETE\n"
        f"Radio: {radio.VENDOR} {radio.MODEL}"
        + (f" {radio.VARIANT}" if getattr(radio, "VARIANT", "") else "")
        + "\n"
        f"Identity check: {identity.get('level', 'unknown')} ({identity.get('reason', '')})\n"
        f"Written raw SHA-256: {expected_hash}\n"
        "Post-write full-image reread: not requested"
    )






def _feature_bool(rf, name, default=False):
    try:
        return bool(getattr(rf, name))
    except Exception:
        return default


def _feature_seq(rf, name):
    try:
        return list(getattr(rf, name) or [])
    except Exception:
        return []



def _editor_radio_views(radio):
    """Return flattened editor views for CHIRP radios with sub-devices."""
    try:
        has_sub = bool(getattr(radio.get_features(), "has_sub_devices", False))
    except Exception:
        has_sub = False
    if not has_sub:
        try:
            lo, hi = [int(x) for x in radio.get_features().memory_bounds]
        except Exception:
            lo, hi = 0, -1
        return [(radio, lo, hi, lo, hi, str(_safe_attr(radio, "VARIANT", "") or ""))]
    try:
        children = list(radio.get_sub_devices() or [])
    except Exception:
        children = []
    if not children:
        try:
            lo, hi = [int(x) for x in radio.get_features().memory_bounds]
        except Exception:
            lo, hi = 0, -1
        return [(radio, lo, hi, lo, hi, str(_safe_attr(radio, "VARIANT", "") or ""))]
    views = []
    next_display = None
    for child in children:
        crf = child.get_features()
        nlo, nhi = [int(x) for x in crf.memory_bounds]
        count = max(0, nhi - nlo + 1)
        dlo = nlo if next_display is None else next_display
        dhi = dlo + count - 1
        views.append((child, dlo, dhi, nlo, nhi, str(_safe_attr(child, "VARIANT", "") or "")))
        next_display = dhi + 1
    return views


def _normalized_valid_bands(radio):
    bands = []
    try:
        for lo, hi in _feature_seq(radio.get_features(), "valid_bands"):
            bands.append((int(lo), int(hi)))
    except Exception:
        pass
    return tuple(sorted(bands))


def _subdevice_capability_signature(radio):
    rf = radio.get_features()
    return (
        _normalized_valid_bands(radio),
        tuple(str(x) for x in _feature_seq(rf, "valid_modes")),
        tuple(str(x) for x in _feature_seq(rf, "valid_duplexes")),
        tuple(str(x) for x in _feature_seq(rf, "valid_power_levels")),
        int(_safe_int(_safe_attr(rf, "valid_name_length", 0), 0)),
    )


def _subdevice_integrity_sensitive(root_radio):
    views = _editor_radio_views(root_radio)
    if len(views) <= 1:
        return False
    signatures = {_subdevice_capability_signature(view) for view, *_ in views}
    return len(signatures) > 1


def _freq_in_bands(freq_hz, bands):
    value = int(freq_hz)
    return any(int(lo) <= value < int(hi) for lo, hi in bands)


def _format_bands_mhz(bands):
    out = []
    for lo, hi in bands:
        out.append(f"{lo / 1_000_000:g}-{hi / 1_000_000:g} MHz")
    return ", ".join(out)




def _validate_memory_subdevice_bands(radio, mem, sub_label=""):
    """Reject RX/TX frequencies outside this child's declared bands.

    This guard is intentionally narrow: it only applies when the driver gives
    this sub-device explicit valid_bands. It does not invent band limits.
    """
    bands = _normalized_valid_bands(radio)
    if not bands or bool(_safe_attr(mem, "empty", False)):
        return
    label = str(sub_label or _safe_attr(radio, "VARIANT", "") or "this sub-device")
    if not _freq_in_bands(mem.freq, bands):
        raise ValueError(
            f"{label} memory cannot use {mem.freq / 1_000_000:.6f} MHz; "
            f"allowed range: {_format_bands_mhz(bands)}."
        )
    duplex = str(_safe_attr(mem, "duplex", "") or "")
    tx = None
    if duplex == "split":
        tx = int(_safe_attr(mem, "offset", 0) or 0)
    elif duplex == "+":
        tx = int(mem.freq) + int(_safe_attr(mem, "offset", 0) or 0)
    elif duplex == "-":
        tx = int(mem.freq) - int(_safe_attr(mem, "offset", 0) or 0)
    if tx is not None and not _freq_in_bands(tx, bands):
        raise ValueError(
            f"{label} memory TX frequency {tx / 1_000_000:.6f} MHz is outside "
            f"its allowed range: {_format_bands_mhz(bands)}."
        )




def _validate_radio_memories_for_write(root_radio):
    """Fail closed before sync_out using the exact loaded CHIRP driver.

    Every populated ordinary memory is passed through the owning radio/sub-device
    validate_memory(). Any CHIRP ValidationError blocks the write. Driver-declared
    valid_bands are also enforced explicitly so a driver-specific validator cannot
    accidentally omit the generic RX/TX boundary check. ValidationWarning objects
    remain advisory, matching CHIRP semantics.
    """
    errors = []
    warnings = []
    checked = 0

    for view, _dlo, _dhi, nlo, nhi, variant in _editor_radio_views(root_radio):
        bands = _normalized_valid_bands(view)
        label = str(variant or _safe_attr(view, "VARIANT", "") or
                    f"{_safe_attr(view, 'VENDOR', '')} {_safe_attr(view, 'MODEL', '')}").strip()
        for native_n in range(int(nlo), int(nhi) + 1):
            try:
                mem = view.get_memory(native_n)
            except Exception as exc:
                errors.append(f"{label or 'Radio'} memory {native_n}: cannot read memory for validation: {exc}")
                continue
            if bool(_safe_attr(mem, "empty", False)):
                continue
            checked += 1
            prefix = f"{label + ' ' if label else ''}memory {native_n}"

            # Enforce the exact band's feature contract even if a driver override
            # of validate_memory() forgets to call the CHIRP base implementation.
            if bands:
                try:
                    _validate_memory_subdevice_bands(view, mem, label)
                except Exception as exc:
                    errors.append(f"{prefix}: {exc}")

            try:
                problems = list(view.validate_memory(mem) or [])
            except Exception as exc:
                errors.append(f"{prefix}: driver validation failed: {exc}")
                continue
            for problem in problems:
                kind = problem.__class__.__name__
                text = str(problem)
                if kind == "ValidationError":
                    errors.append(f"{prefix}: {text}")
                elif kind == "ValidationWarning":
                    warnings.append(f"{prefix}: {text}")

    if errors:
        # Keep the exception readable in Android while retaining enough detail
        # to identify every bad memory in a normal handheld codeplug.
        shown = errors[:25]
        suffix = f"; plus {len(errors)-len(shown)} more" if len(errors) > len(shown) else ""
        raise ValueError(
            "WRITE BLOCKED BY CHIRP DRIVER VALIDATION: " + "; ".join(shown) + suffix
        )
    return {"checked": checked, "warnings": warnings}

def _editor_memory_target(root_radio, display_number):
    n = int(display_number)
    for view, dlo, dhi, nlo, nhi, variant in _editor_radio_views(root_radio):
        if dlo <= n <= dhi:
            return view, nlo + (n - dlo), variant
    raise ValueError(f"Memory {n} is outside this radio's memory range.")

def _editor_memory_dict(view, native_number, display_number, variant="", view_index=0):
    """Serialize one ordinary numeric memory with stable sub-device identity."""
    row = _memory_dict(view, native_number)
    row["nativeNumber"] = int(native_number)
    row["nativeKey"] = int(native_number)
    row["number"] = int(display_number)          # legacy/UI routing slot; keep unique across flattened sub-devices
    row["displayNumber"] = int(display_number)
    # UNIVERSAL SUB-DEVICE CHANNEL LABEL RULE: ordinary channel rows must display
    # the child radio's native memory number, not PocketCHIRP's flattened routing
    # slot. Internal uniqueness is preserved by subDeviceIndex + nativeNumber and
    # memoryId. Do not apply this to named/special memories.
    row["displayLabel"] = str(native_number)
    row["special"] = False
    row["movable"] = True
    row["subDeviceIndex"] = int(view_index)
    row["memoryId"] = f"view:{int(view_index)}:number:{int(native_number)}"
    bands = _normalized_valid_bands(view)
    row["subDeviceBandsMHz"] = [[lo / 1_000_000.0, hi / 1_000_000.0] for lo, hi in bands]
    if variant:
        row["subDevice"] = variant
    return row


def _editor_special_memory_dict(view, special_name, variant="", view_index=0):
    """Serialize a CHIRP named/special channel without flattening its identity."""
    key = str(special_name)
    row = _memory_dict(view, key)
    # CHIRP drivers commonly return a numeric Memory.number for a special
    # channel plus Memory.extd_number containing the stable special name.
    # Keep both. `number` remains display-friendly for existing Android code,
    # while nativeNumber/nativeKey/memoryId preserve the driver's identity.
    row["number"] = key
    row["displayNumber"] = key
    row["displayLabel"] = str(row.get("extdNumber") or key)
    row["nativeKey"] = key
    row["special"] = True
    row["movable"] = False
    row["subDeviceIndex"] = int(view_index)
    row["memoryId"] = f"view:{int(view_index)}:special:{key}"
    bands = _normalized_valid_bands(view)
    row["subDeviceBandsMHz"] = [[lo / 1_000_000.0, hi / 1_000_000.0] for lo, hi in bands]
    if variant:
        row["subDevice"] = variant
    return row


def _editor_memory_target_from_data(root_radio, data):
    """Resolve an editor JSON row back to the exact CHIRP radio/location."""
    memory_id = str(data.get("memoryId", "") or "")
    is_special = bool(data.get("special", False)) or ":special:" in memory_id or memory_id.startswith("special:")
    if not is_special:
        # Stable sub-device identity must win over flattened display numbering.
        # Flattened offsets can legitimately move while a multi-record edit adds
        # contacts/groups/zones/scans and expands a child view's visible bounds.
        # Using the view:N:number:M id keeps every queued edit bound to the exact
        # destination sub-device/native slot. This is generic editor plumbing,
        # not DMR-specific policy.
        if memory_id.startswith("view:") and ":number:" in memory_id:
            return _editor_memory_target_from_id(root_radio, memory_id)
        display_n = int(data["number"])
        return _editor_memory_target(root_radio, display_n)

    views = _editor_radio_views(root_radio)
    try:
        view_index = int(data.get("subDeviceIndex", 0) or 0)
    except Exception:
        view_index = 0
    if view_index < 0 or view_index >= len(views):
        raise ValueError("Special memory references an unknown radio sub-device.")
    radio, _dlo, _dhi, _nlo, _nhi, variant = views[view_index]
    native_key = data.get("nativeKey") or data.get("extdNumber") or data.get("number")
    native_key = str(native_key or "")
    if not native_key:
        raise ValueError("Special memory has no native channel name.")
    valid_specials = [str(x) for x in _feature_seq(radio.get_features(), "valid_special_chans")]
    if valid_specials and native_key not in valid_specials:
        raise ValueError("Unknown special memory: " + native_key)
    return radio, native_key, variant


# ===========================================================================
# CHIRP import-compatibility adapter state
# ===========================================================================
# The proprietary application owns source discovery/parsing and passes neutral
# memory plans here. This state exists only long enough to let CHIRP evaluate
# destination-driver compatibility and apply the user-selected candidates.

_import_candidates = []
_import_source_name = ""



def _candidate_source_features():
    """Return the broad feature set used by CHIRP's generic CSV source."""
    from chirp.drivers.generic_csv import CSVRadio
    return CSVRadio(None).get_features()


def _memory_export_dict(mem):
    return {
        "number": int(mem.number),
        "name": str(mem.name or ""),
        "freq": int(mem.freq),
        "freqMHz": float(mem.freq) / 1_000_000.0,
        "duplex": str(mem.duplex or ""),
        "offset": int(mem.offset or 0),
        "offsetMHz": float(mem.offset or 0) / 1_000_000.0,
        "tmode": str(mem.tmode or ""),
        "rtone": float(mem.rtone),
        "ctone": float(mem.ctone),
        "dtcs": int(mem.dtcs),
        "rx_dtcs": int(mem.rx_dtcs),
        "dtcs_polarity": str(mem.dtcs_polarity or "NN"),
        "cross_mode": str(mem.cross_mode or "Tone->Tone"),
        "mode": str(mem.mode or "FM"),
        "tuning_step": float(mem.tuning_step),
        "skip": str(mem.skip or ""),
        "power": str(mem.power) if mem.power is not None else "",
        "comment": str(mem.comment or ""),
    }



























def _memory_diff(src, dst):
    """Describe meaningful changes CHIRP made to fit a destination radio."""
    fields = (
        ("name", "Name"),
        ("freq", "Frequency"),
        ("duplex", "Duplex"),
        ("offset", "Offset"),
        ("tmode", "Tone mode"),
        ("rtone", "TX tone"),
        ("ctone", "RX tone"),
        ("dtcs", "DCS"),
        ("rx_dtcs", "RX DCS"),
        ("dtcs_polarity", "DCS polarity"),
        ("cross_mode", "Cross mode"),
        ("mode", "Mode"),
        ("tuning_step", "Tuning step"),
        ("skip", "Skip"),
    )
    changes = []
    for attr, label in fields:
        a = getattr(src, attr, None)
        b = getattr(dst, attr, None)
        if a != b:
            changes.append(f"{label}: {a} -> {b}")

    # Power is intentionally not used to classify an otherwise compatible
    # import as "convertible". Generic CSV and network sources frequently do
    # not carry a meaningful handheld power level, and CHIRP will choose the
    # closest/default destination level during import.
    return changes


def _sanity_problem(mem):
    """Catch obviously bad source data before it reaches a radio image."""
    if mem.freq <= 0:
        return "Frequency is missing or invalid."
    if mem.duplex in ("+", "-"):
        off = abs(int(mem.offset or 0))
        # Same practical limit CHIRP's import logic uses while converting splits.
        if mem.freq <= 500_000_000 and off > 15_000_000:
            return f"Offset is abnormally large ({off / 1_000_000:.3f} MHz)."
        if 500_000_000 < mem.freq <= 3_000_000_000 and off > 50_000_000:
            return f"Offset is abnormally large ({off / 1_000_000:.3f} MHz)."
    return ""


def _source_features_for_index(source_features, index):
    """Return per-memory source features when an image has sub-devices."""
    if isinstance(source_features, (list, tuple)):
        if 0 <= int(index) < len(source_features):
            return source_features[int(index)]
        return _candidate_source_features()
    return source_features


def _portable_memory_copy(mem, number=0):
    """Copy portable CHIRP memory semantics, excluding driver-specific extras."""
    try:
        out = mem.dupe()
    except Exception:
        import copy as _copy
        out = _copy.deepcopy(mem)
    out.number = int(number)
    out.empty = False
    try:
        out.extd_number = ""
    except Exception:
        pass
    try:
        out.immutable = []
    except Exception:
        pass
    try:
        out.extra = []
    except Exception:
        pass
    return out


def _semantic_prepare_for_destination(dst_radio, src_mem):
    """Translate exact/equivalent channel semantics to the destination model.

    Active CTCSS/DCS values and out-of-band frequencies are never approximated.
    Only inactive placeholders, derived tuning-step metadata, and clearly
    equivalent CHIRP representations are rewritten.
    """
    from chirp import chirp_common

    mem = _portable_memory_copy(src_mem, getattr(src_mem, "number", 0))
    rf = dst_radio.get_features()
    changes = []

    def changed(label, old, new):
        if old != new:
            changes.append(f"{label}: {old} -> {new}")

    valid_modes = list(getattr(rf, "valid_modes", []) or [])
    if valid_modes and mem.mode not in valid_modes and mem.mode != "Auto":
        mode_equiv = {
            "FM": ("NFM",),
            "NFM": ("FM",),
            "AM": ("NAM",),
            "NAM": ("AM",),
        }
        for candidate in mode_equiv.get(mem.mode, ()):
            if candidate in valid_modes:
                old = mem.mode
                mem.mode = candidate
                changed("Mode", old, candidate)
                break

    valid_duplexes = list(getattr(rf, "valid_duplexes", []) or [])
    if mem.duplex in ("+", "-") and valid_duplexes and mem.duplex not in valid_duplexes and "split" in valid_duplexes:
        tx = int(mem.freq) + (int(mem.offset) if mem.duplex == "+" else -int(mem.offset))
        old = f"{mem.duplex}{int(mem.offset)}"
        mem.duplex = "split"
        mem.offset = tx
        changed("Duplex/offset", old, f"split:{tx}")

    valid_steps = list(getattr(rf, "valid_tuning_steps", []) or [])
    if valid_steps and not bool(getattr(rf, "has_nostep_tuning", False)):
        try:
            required = chirp_common.required_step(int(mem.freq), allowed=valid_steps)
        except Exception:
            required = None
        if required is not None and mem.tuning_step not in valid_steps:
            old = mem.tuning_step
            mem.tuning_step = float(required)
            changed("Tuning step", old, mem.tuning_step)

    tmode = str(getattr(mem, "tmode", "") or "")
    cross = str(getattr(mem, "cross_mode", "Tone->Tone") or "Tone->Tone")
    left, _, right = cross.partition("->")
    tone_tx_active = tmode in ("Tone", "TSQL", "TSQL-R") or (tmode == "Cross" and left == "Tone")
    tone_rx_active = tmode in ("TSQL", "TSQL-R") or (tmode == "Cross" and right == "Tone")
    dtcs_tx_active = tmode in ("DTCS", "DTCS-R") or (tmode == "Cross" and left == "DTCS")
    dtcs_rx_active = tmode in ("DTCS", "DTCS-R") or (tmode == "Cross" and right == "DTCS")

    valid_tones = list(getattr(rf, "valid_tones", []) or [])
    if valid_tones:
        tone_default = 88.5 if 88.5 in valid_tones else float(valid_tones[0])
        if not tone_tx_active and mem.rtone not in valid_tones:
            old = mem.rtone
            mem.rtone = float(tone_default)
            changed("Inactive TX tone", old, mem.rtone)
        if not tone_rx_active and mem.ctone not in valid_tones:
            old = mem.ctone
            mem.ctone = float(tone_default)
            changed("Inactive RX tone", old, mem.ctone)

    valid_dtcs = list(getattr(rf, "valid_dtcs_codes", []) or [])
    if valid_dtcs:
        dtcs_default = 23 if 23 in valid_dtcs else int(valid_dtcs[0])
        if not dtcs_tx_active and mem.dtcs not in valid_dtcs:
            old = mem.dtcs
            mem.dtcs = int(dtcs_default)
            changed("Inactive DCS", old, mem.dtcs)
        if not dtcs_rx_active and mem.rx_dtcs not in valid_dtcs:
            old = mem.rx_dtcs
            mem.rx_dtcs = int(dtcs_default)
            changed("Inactive RX DCS", old, mem.rx_dtcs)

    valid_pols = list(getattr(rf, "valid_dtcs_pols", []) or [])
    if valid_pols and not (dtcs_tx_active or dtcs_rx_active) and mem.dtcs_polarity not in valid_pols:
        default_pol = "NN" if "NN" in valid_pols else str(valid_pols[0])
        old = mem.dtcs_polarity
        mem.dtcs_polarity = default_pol
        changed("Inactive DCS polarity", old, mem.dtcs_polarity)

    valid_skips = list(getattr(rf, "valid_skips", []) or [])
    if valid_skips and mem.skip not in valid_skips:
        default_skip = "" if "" in valid_skips else str(valid_skips[0])
        old = mem.skip
        mem.skip = default_skip
        changed("Scan skip", old, mem.skip)

    return mem, changes


def _destination_preview_targets(dst_radio):
    """Return ordinary destination slots ranked from safest to most restricted.

    Import preview must validate against a real destination slot because CHIRP
    drivers may impose per-memory immutable policy.  Prefer empty, fully mutable
    slots, then occupied mutable slots, and only then restricted slots.  This
    avoids falsely rejecting an otherwise portable memory just because channel 1
    happens to be fixed by a service-specific driver variant.
    """
    rf = dst_radio.get_features()
    low, high = [int(x) for x in rf.memory_bounds]
    ranked = [[], [], [], []]
    for number in range(low, high + 1):
        try:
            current = dst_radio.get_memory(number)
        except Exception:
            continue
        immutable = set(getattr(current, "immutable", []) or [])
        empty = bool(getattr(current, "empty", False))
        bucket = 0 if empty and not immutable else 1 if (not empty and not immutable) else 2 if empty else 3
        ranked[bucket].append(number)
    return [n for bucket in ranked for n in bucket]


def _import_candidate_for_target(dst_radio, candidate, target, fallback_features=None):
    """Convert one preview/apply candidate for one concrete destination slot."""
    from chirp import import_logic
    original_src = candidate["source"]
    src = candidate.get("prepared") or original_src
    candidate_features = candidate.get("source_features") or fallback_features or _candidate_source_features()
    return import_logic.import_mem(
        dst_radio, candidate_features, src,
        overrides={"number": int(target)}
    )


def _is_destination_slot_policy_error(exc):
    """True when a failure is about this physical destination slot, not source data."""
    try:
        from chirp import chirp_common
        if isinstance(exc, chirp_common.ImmutableValueError):
            return True
    except Exception:
        pass
    text = str(exc or "").lower()
    markers = (
        "not mutable", "immutable", "read-only", "read only",
        "fixed channel", "fixed memory", "cannot be changed",
        "can't be changed", "protected memory", "protected channel",
    )
    return any(marker in text for marker in markers)


def _build_unvalidated_import_preview(source_name, memories, metadata=None, limit=1000):
    """Return source rows without claiming destination compatibility.

    This deliberately does not populate _import_candidates. Placement remains
    impossible until the same neutral plan is previewed again with a loaded
    destination image.
    """
    rows = []
    metadata = metadata or []
    display_limit = max(1, min(int(limit or 1000), 5000))
    for i, src in enumerate(memories[:display_limit]):
        meta = metadata[i] if i < len(metadata) else {}
        row = _memory_export_dict(src)
        row.update({
            "id": i,
            "sourceNumber": int(getattr(src, "number", i)),
            "status": "pending",
            "reason": "",
            "changes": [],
            "source": source_name,
            "meta": meta,
            "previewTarget": None,
        })
        rows.append(row)
    return _json.dumps({
        "source": source_name,
        "count": len(rows),
        "compatible": 0,
        "convertible": 0,
        "unsupported": 0,
        "items": rows,
        "totalResultCount": len(memories),
        "displayLimit": display_limit,
        "truncated": len(memories) > len(rows),
        "destinationValidated": False,
    })


def _build_import_preview(source_name, memories, source_features, metadata=None, limit=1000):
    global _import_candidates, _import_source_name
    from chirp import import_logic

    dst = _radio_from_image_bytes()
    dst_rf = dst.get_features()
    low, high = [int(x) for x in dst_rf.memory_bounds]
    preview_targets = _destination_preview_targets(dst)
    rows = []
    _import_candidates = []
    _import_source_name = source_name
    metadata = metadata or []
    display_limit = max(1, min(int(limit or 1000), 5000))

    for i, src in enumerate(memories[:display_limit]):
        meta = metadata[i] if i < len(metadata) else {}
        src_features = _source_features_for_index(source_features, i)
        reason = _sanity_problem(src)
        converted = None
        prepared = src
        changes = []
        status = "unsupported" if reason else "compatible"
        preview_target = None

        if not reason:
            try:
                prepared, semantic_changes = _semantic_prepare_for_destination(dst, src)
                candidate_probe = {
                    "source": src,
                    "prepared": prepared,
                    "source_features": src_features,
                }
                last_exc = None
                # Ask the destination driver itself. If an early slot is fixed,
                # keep looking for a normal writable ordinary memory.
                for target in preview_targets:
                    try:
                        converted = _import_candidate_for_target(
                            dst, candidate_probe, target, src_features)
                        preview_target = int(target)
                        last_exc = None
                        break
                    except Exception as exc:
                        last_exc = exc
                        # A fixed/protected physical slot may reject an otherwise
                        # valid memory. Only that kind of error justifies probing
                        # another slot. Source-data validation errors are global
                        # for this destination model and should fail immediately.
                        if _is_destination_slot_policy_error(exc):
                            continue
                        raise
                if converted is None:
                    if last_exc is not None:
                        raise last_exc
                    raise ValueError("No ordinary destination memory can accept this channel.")

                changes = list(semantic_changes)
                for item in _memory_diff(src, converted):
                    if item not in changes:
                        changes.append(item)
                if changes:
                    status = "convertible"
            except Exception as exc:
                status = "unsupported"
                reason = str(exc)

        candidate = {
            "source": src,
            "prepared": prepared,
            "source_features": src_features,
            "converted": converted,
            "status": status,
            "reason": reason,
            "meta": meta,
            "preview_target": preview_target,
        }
        candidate_id = len(_import_candidates)
        _import_candidates.append(candidate)

        shown = converted if converted is not None else src
        row = _memory_export_dict(shown)
        row.update({
            "id": candidate_id,
            "sourceNumber": int(getattr(src, "number", i)),
            "status": status,
            "reason": reason,
            "changes": changes,
            "source": source_name,
            "meta": meta,
            "previewTarget": preview_target,
        })
        rows.append(row)

    return _json.dumps({
        "source": source_name,
        "count": len(rows),
        "compatible": sum(1 for x in rows if x["status"] == "compatible"),
        "convertible": sum(1 for x in rows if x["status"] == "convertible"),
        "unsupported": sum(1 for x in rows if x["status"] == "unsupported"),
        "memoryBounds": [low, high],
        "items": rows,
        "totalResultCount": len(memories),
        "displayLimit": display_limit,
        "truncated": len(memories) > len(rows),
        "destinationValidated": True,
    })






































def apply_import_candidates_json(ids_json, mode="first_empty"):
    """Apply selected preview candidates to the working image only.

    Placement modes:
      first_empty       - fill only currently empty ordinary memories.
      specific:N        - one selected source to exactly channel N.
      start_overwrite:N - selected sources in order from N upward, replacing
                          occupied memories as needed and skipping slots which
                          the destination driver rejects as fixed/protected.
      overwrite         - same as start_overwrite at the first ordinary memory.
      replace_all       - clear every deletable ordinary memory first, then place
                          selected usable sources from the beginning. Protected
                          and special memories are left alone.

    Unsupported preview rows never consume a destination slot. If a destination
    slot has model-specific restrictions, automatic modes try the next slot.
    """
    global _import_candidates
    import copy as _copy

    if not _last_image_bytes:
        raise ValueError("No working radio image is loaded.")
    if not _import_candidates:
        raise ValueError("There is no import preview to apply.")

    ids = _json.loads(ids_json) if isinstance(ids_json, str) else ids_json
    ids = [int(x) for x in ids]
    if not ids:
        raise ValueError("Select at least one compatible result first.")

    selected = []
    skipped_preview = []
    for cid in ids:
        if cid < 0 or cid >= len(_import_candidates):
            continue
        candidate = _import_candidates[cid]
        if candidate["status"] == "unsupported":
            skipped_preview.append({"id": cid, "reason": candidate.get("reason") or "Unsupported"})
            continue
        selected.append((cid, candidate))
    if not selected:
        raise ValueError("None of the selected results are compatible with this radio.")

    radio = _radio_from_image_bytes()
    rf = radio.get_features()
    low, high = [int(x) for x in rf.memory_bounds]
    source_features = _candidate_source_features()
    mode = str(mode or "first_empty")

    exact_target = None
    start_target = low
    replace_all = False
    empty_only = False

    if mode.startswith("specific:"):
        if len(selected) != 1:
            raise ValueError("Specific-channel import requires exactly one selected result.")
        try:
            exact_target = int(mode.split(":", 1)[1])
        except Exception:
            raise ValueError("Invalid destination channel.")
        if exact_target < low or exact_target > high:
            raise ValueError(f"Destination channel {exact_target} is outside the valid range {low}-{high}.")
    elif mode.startswith("start_overwrite:"):
        try:
            start_target = int(mode.split(":", 1)[1])
        except Exception:
            raise ValueError("Invalid starting destination channel.")
        if start_target < low or start_target > high:
            raise ValueError(f"Starting channel {start_target} is outside the valid range {low}-{high}.")
    elif mode == "overwrite":
        start_target = low
    elif mode == "first_empty":
        empty_only = True
    elif mode == "replace_all":
        replace_all = True
        start_target = low
    else:
        raise ValueError("Unknown import mode: " + mode)

    cleared = 0
    protected_targets = []
    if replace_all:
        # Work only on this temporary radio object. If the import later fails
        # completely, _save_working_radio is never called, so the user's working
        # image is not partially cleared.
        for number in range(low, high + 1):
            try:
                old = radio.get_memory(number)
            except Exception as exc:
                protected_targets.append({"number": number, "reason": str(exc)})
                continue
            if bool(getattr(old, "empty", False)):
                continue
            immutable = set(getattr(old, "immutable", []) or [])
            # Treat any immutable ordinary memory as protected during a
            # whole-list replacement. The user asked to replace the editable
            # channel list, not to defeat service/factory fixed memories.
            if immutable:
                protected_targets.append({
                    "number": number,
                    "reason": "Protected memory: " + ", ".join(sorted(immutable)),
                })
                continue
            try:
                mem = _copy.deepcopy(old)
            except Exception:
                mem = old.dupe() if hasattr(old, "dupe") else old
            try:
                mem.empty = True
                radio.check_set_memory_immutable_policy(old, mem)
                radio.set_memory(mem)
                cleared += 1
            except Exception as exc:
                protected_targets.append({"number": number, "reason": str(exc)})

    if exact_target is not None:
        target_pool = [exact_target]
    else:
        target_pool = []
        for number in range(start_target, high + 1):
            try:
                current = radio.get_memory(number)
            except Exception:
                continue
            if empty_only and not bool(getattr(current, "empty", False)):
                continue
            target_pool.append(number)

    if not target_pool:
        if empty_only:
            raise ValueError("There are no empty ordinary destination channels available.")
        raise ValueError("There are no ordinary destination channels available.")

    imported = 0
    conversions = 0
    imported_targets = []
    skipped_candidates = list(skipped_preview)
    skipped_slot_reasons = []
    next_index = 0

    for cid, candidate in selected:
        original_src = candidate["source"]
        placed = False
        last_error = None

        # Exact placement gets exactly one attempt. Automatic placement keeps
        # moving forward; a protected destination does not consume the source.
        scan_start = next_index
        for pool_index in range(scan_start, len(target_pool)):
            target = int(target_pool[pool_index])
            try:
                dest = _import_candidate_for_target(
                    radio, candidate, target,
                    candidate.get("source_features") or source_features)
                radio.set_memory(dest)
                if _memory_diff(original_src, dest):
                    conversions += 1
                imported += 1
                imported_targets.append(target)
                placed = True
                next_index = pool_index + 1
                break
            except Exception as exc:
                last_error = exc
                if exact_target is not None:
                    break
                if _is_destination_slot_policy_error(exc):
                    skipped_slot_reasons.append({
                        "candidateId": cid,
                        "target": target,
                        "reason": str(exc),
                    })
                    # This physical slot is protected for this memory shape;
                    # skip it and keep the same source candidate for the next
                    # destination. It will not create a source-side hole.
                    next_index = pool_index + 1
                    continue
                # This is not a slot-policy failure. Do not burn destination
                # channels trying the same source everywhere; skip the source
                # candidate and let the next usable source try this target.
                break

        if not placed:
            skipped_candidates.append({
                "id": cid,
                "reason": str(last_error) if last_error else "No acceptable destination channel remained",
            })
            if exact_target is not None:
                raise ValueError(
                    f"Destination channel {exact_target} cannot accept the selected memory: "
                    + skipped_candidates[-1]["reason"]
                )

    if imported <= 0:
        raise ValueError("No selected memories could be placed in the destination radio.")

    _save_working_radio(radio)
    return _json.dumps({
        "imported": imported,
        "converted": conversions,
        "mode": mode,
        "source": _import_source_name,
        "targetNumbers": imported_targets,
        "skipped": skipped_candidates,
        "skippedCount": len(skipped_candidates),
        "protectedTargets": protected_targets,
        "slotRejects": skipped_slot_reasons,
        "cleared": cleared,
        "state": _json.loads(pocketchirp_radio_document_json()),
    })



# =============================================================================
# STATIC COMPANION ENGINE RUNTIME
# =============================================================================
# Production companion builds execute only the bridge.py packaged in the GPL
# engine APK. PocketCHIRP cannot replace Python engine code at runtime; CHIRP or
# bridge changes require an explicit engine APK update.
# =============================================================================

# =============================================================================
# POCKETCHIRP ENGINE RPC BOUNDARY - STAGE 2
# =============================================================================
# This is the language-neutral application/engine contract. Normal PocketCHIRP
# application operations enter through a versioned JSON envelope. The Android
# application no longer needs to know Python function/object details.
#
# IMPORTANT: the four live-radio operations which still receive an Android
# transport object are intentionally NOT exposed here. They remain isolated in
# PocketChirpEngineClient.invokeLiveTransport() until the transport boundary is
# moved into a separate Android service/process.
# =============================================================================
POCKETCHIRP_ENGINE_RPC_INTERFACE = 1

_POCKETCHIRP_ENGINE_RPC_OPERATIONS = frozenset({
    "selected_driver_identification_payloads_json",
    "selected_radio_prompt_contract_json",
    "selected_serial_driver_facts_json",
    "selected_native_usb_driver_facts_json",
    "update_memory_json",
    "delete_memories_json",
    "update_setting_json",
    "stock_config_catalog_json",
    "preview_stock_config_json",
    "rearrange_memories_json",
    "set_bank_json",
        "unregister_custom_driver_runtime_json",
        "select_radio",
    "apply_import_candidates_json",
    "radio_catalog_json",
    "pocketchirp_bridge_revision",
    "pocketchirp_bridge_compat_version",
    "pocketchirp_radio_constraints_json",
    "preview_pocketchirp_memories_json",
    "pocketchirp_radio_document_json",
    "materialize_editor_edits_b64_json",
})


def pocketchirp_engine_request_json(request_json):
    """Execute one versioned, JSON-safe PocketCHIRP engine request.

    The wire contract intentionally supports only JSON values. Java transport
    objects, Python objects, CHIRP classes, and arbitrary function names cannot
    cross this entrypoint.
    """
    try:
        request = _json.loads(str(request_json).lstrip("\ufeff"))
        if not isinstance(request, dict):
            raise ValueError("Engine request must be a JSON object.")
        version = int(request.get("interfaceVersion", 0) or 0)
        if version != POCKETCHIRP_ENGINE_RPC_INTERFACE:
            raise ValueError(
                "Unsupported PocketCHIRP engine interface version %s; expected %s."
                % (version, POCKETCHIRP_ENGINE_RPC_INTERFACE)
            )
        operation = str(request.get("operation") or "").strip()
        if operation not in _POCKETCHIRP_ENGINE_RPC_OPERATIONS:
            raise ValueError("Engine operation is not exposed by the neutral API: " + operation)
        args = request.get("args", [])
        if not isinstance(args, list):
            raise ValueError("Engine request args must be a JSON array.")
        fn = globals().get(operation)
        if not callable(fn):
            raise RuntimeError("Engine operation is unavailable in this runtime: " + operation)
        result = fn(*args)
        return _json.dumps({
            "ok": True,
            "interfaceVersion": POCKETCHIRP_ENGINE_RPC_INTERFACE,
            "operation": operation,
            "result": result,
        }, separators=(",", ":"))
    except Exception as exc:
        return _json.dumps({
            "ok": False,
            "interfaceVersion": POCKETCHIRP_ENGINE_RPC_INTERFACE,
            "errorType": exc.__class__.__name__,
            "error": str(exc),
        }, separators=(",", ":"))




def pocketchirp_radio_constraints_json():
    """Return neutral editing constraints for the currently loaded radio image."""
    if not _last_image_bytes:
        raise ValueError("Read a radio or load a .img first.")
    radio = _radio_from_image_bytes()
    rf = radio.get_features()
    steps_hz = []
    for value in list(getattr(rf, "valid_tuning_steps", []) or []):
        try:
            hz = float(value) * 1000.0
            if hz > 0:
                steps_hz.append(hz)
        except Exception:
            continue
    steps_hz = sorted(set(steps_hz))
    bands = []
    for item in list(getattr(rf, "valid_bands", []) or []):
        try:
            lo, hi = item
            bands.append([int(lo), int(hi)])
        except Exception:
            continue
    return _json.dumps({
        "schemaVersion": 1,
        "minimumTuningStepHz": steps_hz[0] if steps_hz else 0,
        "tuningStepsHz": steps_hz,
        "validBandsHz": bands,
        "validModes": [str(x) for x in list(getattr(rf, "valid_modes", []) or [])],
        "nameLength": int(getattr(rf, "valid_name_length", 0) or 0),
        "validCharacters": _feature_valid_characters_text(rf),
    }, separators=(",", ":"))


def _pocketchirp_memory_from_neutral(row, default_number):
    """Translate one neutral PocketCHIRP memory row to a CHIRP Memory object.

    This function is intentionally an engine adapter. Satellite/repeater/search
    business logic belongs on the PocketCHIRP side; only conversion to CHIRP's
    object model happens here.
    """
    from chirp import chirp_common

    if not isinstance(row, dict):
        raise ValueError("Neutral memory rows must be JSON objects.")
    mem = chirp_common.Memory()
    mem.number = int(row.get("number", default_number))
    mem.name = str(row.get("name") or "")
    if "rxHz" not in row:
        raise ValueError("Neutral memory row is missing rxHz.")
    mem.freq = int(round(float(row.get("rxHz"))))

    tx_hz = row.get("txHz")
    if tx_hz not in (None, "", 0, 0.0):
        tx_hz = int(round(float(tx_hz)))
        representation = str(row.get("txRepresentation") or "split").lower()
        if representation == "auto":
            chirp_common.split_to_offset(mem, mem.freq, tx_hz)
        elif representation == "offset":
            offset = tx_hz - mem.freq
            mem.duplex = "+" if offset >= 0 else "-"
            mem.offset = abs(int(offset))
        else:
            mem.duplex = "split"
            mem.offset = tx_hz
    else:
        duplex = str(row.get("duplex") or "")
        if duplex:
            mem.duplex = duplex
        if row.get("offsetHz") not in (None, ""):
            mem.offset = int(round(float(row.get("offsetHz"))))

    if row.get("mode") not in (None, ""):
        mem.mode = str(row.get("mode"))
    if row.get("skip") not in (None, ""):
        mem.skip = str(row.get("skip"))
    if row.get("comment") not in (None, ""):
        mem.comment = str(row.get("comment"))

    tx_tone = row.get("txToneHz")
    rx_tone = row.get("rxToneHz")
    tone_mode = str(row.get("toneMode") or "").strip()
    if tx_tone not in (None, "", 0, 0.0):
        mem.rtone = float(tx_tone)
        if not tone_mode:
            tone_mode = "Tone"
    if rx_tone not in (None, "", 0, 0.0):
        mem.ctone = float(rx_tone)
        if not tone_mode:
            tone_mode = "TSQL"
    if tone_mode:
        mem.tmode = tone_mode

    if row.get("dtcsCode") not in (None, ""):
        mem.dtcs = int(row.get("dtcsCode"))
    if row.get("rxDtcsCode") not in (None, "") and hasattr(mem, "rx_dtcs"):
        mem.rx_dtcs = int(row.get("rxDtcsCode"))
    if row.get("dtcsPolarity") not in (None, ""):
        mem.dtcs_polarity = str(row.get("dtcsPolarity"))
    if row.get("crossMode") not in (None, ""):
        mem.cross_mode = str(row.get("crossMode"))
    if row.get("tuningStepKhz") not in (None, ""):
        mem.tuning_step = float(row.get("tuningStepKhz"))
    if row.get("powerDbm") not in (None, ""):
        try:
            mem.power = chirp_common.PowerLevel(
                str(row.get("powerLabel") or "Source"),
                dBm=float(row.get("powerDbm")))
        except Exception:
            pass

    # D-STAR/ digital-memory field assignment is CHIRP object-model work and
    # intentionally remains on the GPL engine side.
    for key, attr, numeric in (
            ("dvUrCall", "dv_urcall", False),
            ("dvRpt1Call", "dv_rpt1call", False),
            ("dvRpt2Call", "dv_rpt2call", False),
            ("dvCode", "dv_code", True)):
        value = row.get(key)
        if value in (None, "") or not hasattr(mem, attr):
            continue
        try:
            setattr(mem, attr, int(value) if numeric else str(value))
        except Exception:
            pass
    return mem


def preview_pocketchirp_memories_json(plan_json):
    """Preview PocketCHIRP-owned neutral memories against the selected radio."""
    from chirp.drivers.generic_csv import CSVRadio

    plan = _json.loads(str(plan_json).lstrip("\ufeff"))
    if not isinstance(plan, dict):
        raise ValueError("PocketCHIRP memory plan must be a JSON object.")
    if int(plan.get("schemaVersion", 1) or 1) != 1:
        raise ValueError("Unsupported PocketCHIRP memory-plan schema version.")

    rows = plan.get("memories") or []
    if not isinstance(rows, list):
        raise ValueError("PocketCHIRP memory-plan memories must be an array.")
    if not rows:
        empty = plan.get("emptyResult")
        if isinstance(empty, dict):
            return _json.dumps(empty)
        raise ValueError("PocketCHIRP memory plan contains no memories.")
    memories = [_pocketchirp_memory_from_neutral(row, i) for i, row in enumerate(rows)]

    metadata = plan.get("metadata")
    if metadata is not None and not isinstance(metadata, list):
        raise ValueError("PocketCHIRP memory-plan metadata must be an array.")
    source_name = str(plan.get("sourceName") or "PocketCHIRP")
    limit = int(plan.get("limit", 1000) or 1000)
    limit = max(1, min(limit, 5000))

    if not _last_image_bytes:
        preview = _json.loads(_build_unvalidated_import_preview(
            source_name, memories, metadata=metadata, limit=limit))
        extra = plan.get("extraPreview") or {}
        if isinstance(extra, dict):
            for key, value in extra.items():
                preview[str(key)] = value
        if bool(plan.get("markTruncated", False)):
            preview["truncated"] = len(memories) > int(preview.get("count", 0) or 0)
        return _json.dumps(preview)

    preview = _json.loads(_build_import_preview(
        source_name,
        memories,
        CSVRadio(None).get_features(),
        metadata=metadata,
        limit=limit,
    ))
    extra = plan.get("extraPreview") or {}
    if isinstance(extra, dict):
        for key, value in extra.items():
            preview[str(key)] = value
    if bool(plan.get("markTruncated", False)):
        preview["truncated"] = len(memories) > int(preview.get("count", 0) or 0)
    return _json.dumps(preview)


def _neutral_memory_document_row(row):
    """Convert one CHIRP-facing memory serialization to the neutral app schema.

    This helper intentionally contains no WebView/editor-history policy. The
    input row is produced directly from a CHIRP Memory object and the output is
    a PocketCHIRP Radio Document record.
    """
    neutral = {
        "id": str(row.get("memoryId") or ""),
        "number": row.get("number"),
        "displayLabel": str(row.get("displayLabel") or row.get("number") or ""),
        "special": bool(row.get("special", False)),
        "empty": bool(row.get("empty", False)),
        "immutable": list(row.get("immutable") or []),
        "subDeviceIndex": row.get("subDeviceIndex"),
        "subDevice": str(row.get("subDevice") or ""),
        # Per-memory CHIRP options are part of the neutral channel record even
        # when the slot is empty. The proprietary UI need not know their CHIRP
        # semantics; it simply renders the neutral field descriptors.
        "extraFields": row.get("extra") or [],
    }
    if row.get("readError"):
        neutral["readError"] = str(row.get("readError"))
    if neutral["empty"]:
        return neutral

    rx_hz = int(round(float(row.get("freq", 0) or 0) * 1_000_000.0))
    duplex = str(row.get("duplex") or "")
    offset_hz = int(round(float(row.get("offset", 0) or 0) * 1_000_000.0))
    tx_hz = None
    if duplex == "split":
        tx_hz = offset_hz
    elif duplex == "+":
        tx_hz = rx_hz + offset_hz
    elif duplex == "-":
        tx_hz = rx_hz - offset_hz

    neutral.update({
        "name": str(row.get("name") or ""),
        "rxHz": rx_hz,
        "txHz": tx_hz,
        "duplex": duplex,
        "offsetHz": offset_hz,
        "mode": str(row.get("mode") or ""),
        "toneMode": str(row.get("tmode") or ""),
        "txToneHz": row.get("rtone"),
        "rxToneHz": row.get("ctone"),
        "dtcsCode": row.get("dtcs"),
        "rxDtcsCode": row.get("rx_dtcs"),
        "dtcsPolarity": str(row.get("dtcs_polarity") or ""),
        "crossMode": str(row.get("cross_mode") or ""),
        "powerLabel": str(row.get("power") or ""),
        "powerDbm": row.get("powerDbm"),
        "skip": str(row.get("skip") or ""),
        "tuningStepKhz": row.get("tuning_step"),
        "comment": str(row.get("comment") or ""),
        "dvUrCall": str(row.get("dv_urcall") or ""),
        "dvRpt1Call": str(row.get("dv_rpt1call") or ""),
        "dvRpt2Call": str(row.get("dv_rpt2call") or ""),
        "dvCode": row.get("dv_code"),
    })
    return neutral


def _neutral_constraints_for_views(root_radio, views):
    """Return only radio/driver constraints; no application presentation state."""
    base_radio = views[0][0] if views else root_radio
    rf = base_radio.get_features()

    def union_feature(name):
        out, seen = [], set()
        for view, *_ in views:
            for value in _feature_seq(view.get_features(), name):
                key = str(value)
                if key not in seen:
                    seen.add(key)
                    out.append(value)
        return out

    low = min((v[1] for v in views), default=0)
    high = max((v[2] for v in views), default=-1)
    name_charsets = [
        _feature_valid_characters_text(v[0].get_features()) for v in views
    ]
    common_name_charset = (
        name_charsets[0]
        if name_charsets and all(value == name_charsets[0] for value in name_charsets)
        else ""
    )
    return {
        "nameLength": max([_safe_int(_safe_attr(v[0].get_features(),
                                                "valid_name_length", 0), 0)
                           for v in views] or [0]),
        "validCharacters": common_name_charset,
        "modes": [str(x) for x in union_feature("valid_modes")],
        "tmodes": [str(x) for x in union_feature("valid_tmodes")],
        "duplexes": [str(x) for x in union_feature("valid_duplexes")],
        "skips": [str(x) for x in union_feature("valid_skips")],
        "powers": [str(x) for x in union_feature("valid_power_levels")],
        "tones": [_safe_float(x, 0.0) for x in union_feature("valid_tones")],
        "dtcs": [_safe_int(x, 0) for x in union_feature("valid_dtcs_codes")],
        "crossModes": [str(x) for x in union_feature("valid_cross_modes")],
        "dtcsPolarities": [str(x) for x in union_feature("valid_dtcs_pols")],
        "tuningSteps": [_safe_float(x, 0.0) for x in union_feature("valid_tuning_steps")],
        "specialChannels": [str(x) for x in union_feature("valid_special_chans")],
        "memoryBounds": [low, high],
        "hasName": any(_feature_bool(v[0].get_features(), "has_name", True) for v in views),
        "hasMode": any(_feature_bool(v[0].get_features(), "has_mode", True) for v in views),
        "hasOffset": any(_feature_bool(v[0].get_features(), "has_offset", True) for v in views),
        "hasDtcs": any(_feature_bool(v[0].get_features(), "has_dtcs", True) for v in views),
        "hasRxDtcs": any(_feature_bool(v[0].get_features(), "has_rx_dtcs", False) for v in views),
        "hasDtcsPolarity": any(_feature_bool(v[0].get_features(), "has_dtcs_polarity", False) for v in views),
        "hasCtone": any(_feature_bool(v[0].get_features(), "has_ctone", False) for v in views),
        "hasCross": any(_feature_bool(v[0].get_features(), "has_cross", False) for v in views),
        "hasTuningStep": any(_feature_bool(v[0].get_features(), "has_tuning_step", False) for v in views),
        "hasComment": any(_feature_bool(v[0].get_features(), "has_comment", False) for v in views),
        "hasSettings": _feature_bool(root_radio.get_features(), "has_settings", False),
        "hasBank": False if len(views) > 1 else _feature_bool(rf, "has_bank", False),
        "hasBankNames": False if len(views) > 1 else _feature_bool(rf, "has_bank_names", False),
        "canOddSplit": any(_feature_bool(v[0].get_features(), "can_odd_split", False) for v in views),
        "canDelete": all(_feature_bool(v[0].get_features(), "can_delete", True) for v in views),
        "hasSubDevices": len(views) > 1,
        "subDeviceIntegritySensitive": _subdevice_integrity_sensitive(root_radio),
    }


def pocketchirp_radio_document_json():
    """Export the current CHIRP image directly as neutral Radio Document v1.

    LICENSING/ARCHITECTURE BOUNDARY: this is the direct CHIRP-to-neutral serializer; legacy editor presentation is proprietary.
    CHIRP objects are translated directly to the neutral contract; WebView and
    editor-history presentation remain proprietary application concerns.
    """
    if _radio_catalog_cache is None or not _last_image_bytes:
        return _json.dumps({
            "schemaVersion": 1,
            "loaded": False,
            "radio": None,
            "memories": [],
            "settings": [],
            "banks": [],
            "constraints": {},
            "subDevices": [],
            "metadata": {"selectedRadioKey": _selected_radio_key},
        }, separators=(",", ":"))

    root_radio = _radio_from_image_bytes()
    views = _editor_radio_views(root_radio)
    raw, _ = _split_chirp_img(_last_image_bytes)
    constraints = _neutral_constraints_for_views(root_radio, views)

    memories = []
    sub_devices = []

    def export_native_numbers(view, nlo, nhi):
        """Return the native rows which need materializing in the neutral document.

        Drivers may optionally provide pocketchirp_export_native_numbers() to avoid
        serializing thousands of unused creation slots. The advertised CHIRP
        memory_bounds remain unchanged, so the app can still synthesize targets
        anywhere inside the driver's real/editor capacity.
        """
        hook = getattr(view, "pocketchirp_export_native_numbers", None)
        if callable(hook):
            try:
                out = []
                seen = set()
                for value in hook() or []:
                    number = int(value)
                    if nlo <= number <= nhi and number not in seen:
                        seen.add(number)
                        out.append(number)
                if out:
                    return sorted(out)
            except Exception as exc:
                LOG.warning("Driver export-row hint failed for %s: %s",
                            type(view).__name__, exc)
        return range(nlo, nhi + 1)

    for view_index, (view, dlo, dhi, nlo, nhi, variant) in enumerate(views):
        vrf = view.get_features()
        specials = [str(x) for x in _feature_seq(vrf, "valid_special_chans")]
        bands = _normalized_valid_bands(view)
        sub_devices.append({
            "index": view_index,
            "variant": variant or "Sub-device %d" % (view_index + 1),
            "displayBounds": [dlo, dhi],
            "nativeBounds": [nlo, nhi],
            "validBandsHz": [[int(lo), int(hi)] for lo, hi in bands],
            "validCharacters": _feature_valid_characters_text(vrf),
            "integritySensitive": _subdevice_integrity_sensitive(root_radio),
            "specialChannels": specials,
        })
        for native_n in export_native_numbers(view, nlo, nhi):
            display_n = dlo + (native_n - nlo)
            try:
                row = _editor_memory_dict(view, native_n, display_n, variant, view_index)
            except Exception as exc:
                row = {
                    "number": display_n,
                    "displayLabel": str(native_n),
                    "memoryId": "view:%d:number:%d" % (view_index, native_n),
                    "subDevice": variant,
                    "subDeviceIndex": view_index,
                    "special": False,
                    "empty": True,
                    "immutable": [],
                    "readError": "%s: %s" % (type(exc).__name__, exc),
                }
            memories.append(_neutral_memory_document_row(row))
        for special_name in specials:
            try:
                row = _editor_special_memory_dict(view, special_name, variant, view_index)
            except Exception as exc:
                row = {
                    "number": special_name,
                    "displayLabel": special_name,
                    "memoryId": "view:%d:special:%s" % (view_index, special_name),
                    "subDevice": variant,
                    "subDeviceIndex": view_index,
                    "special": True,
                    "empty": True,
                    "immutable": [],
                    "readError": "%s: %s" % (type(exc).__name__, exc),
                }
            memories.append(_neutral_memory_document_row(row))

    doc = {
        "schemaVersion": 1,
        "loaded": True,
        "radio": {
            "vendor": str(_safe_attr(root_radio, "VENDOR", "") or ""),
            "model": str(_safe_attr(root_radio, "MODEL", "") or ""),
            "variant": str(_safe_attr(root_radio, "VARIANT", "") or ""),
        },
        "memories": memories,
        "settings": _settings_list(root_radio) if constraints["hasSettings"] else [],
        "banks": [] if len(views) > 1 else _bank_state_for_radio(
            root_radio, (views[0][0] if views else root_radio).get_features()),
        "constraints": constraints,
        "subDevices": sub_devices,
        "metadata": {
            "rawBytes": len(raw),
            "rawSha256": hashlib.sha256(raw).hexdigest(),
            "selectedRadioKey": _selected_radio_key,
        },
    }
    return _json.dumps(doc, separators=(",", ":"))
