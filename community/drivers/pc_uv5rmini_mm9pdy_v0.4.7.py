# SPDX-License-Identifier: GPL-2.0-or-later
"""PocketCHIRP community driver, MM9PDY UV-5R Mini, 0.4.7-full-ble-write-beta.
Independent Python implementation of the documented MMZ1/MMZS/MMZO wire format.
Extends CHIRP's GPL Baofeng UV5RMini driver. No Codeplug Studio source included.
Direct USB upload and experimental full native BLE upload (channels, settings and zones) from the image. Both stop after final ACK; no memory reads before or after upload. Automatic edited-region selection by default. Offline codec has no I/O side effects.
"""
import binascii
import base64
import hashlib
import zlib
import logging
import struct
import sys
from functools import wraps
from dataclasses import dataclass

VERSION = '0.4.7-full-ble-write-beta'
BASE_SIZE = 0x8240
ZONE_SIZE = 0x1000
IMAGE_SIZE = BASE_SIZE + ZONE_SIZE
MAX_CHANNEL = 999
MAX_ZONES = 24
LOG = logging.getLogger(__name__)


class ZoneError(ValueError):
    pass


@dataclass(frozen=True)
class Zone:
    name: str
    members: tuple  # one-based physical channel numbers, in scan/display order
    scan: object = None  # None = firmware default; tuple = explicit scan set


def crc(data):
    return binascii.crc_hqx(data, 0)


def u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]


def p16(value):
    return struct.pack('<H', value)


def generation(value):
    return {0: 1, 65535: 65534}.get(value, value)


def _require(condition, message):
    if not condition:
        raise ZoneError(message)


def _bits(data, width, count, pos=0):
    values = []
    for _ in range(count):
        value = 0
        for i in range(width):
            value |= ((data[pos // 8] >> (pos % 8)) & 1) << i
            pos += 1
        values.append(value)
    return values, pos


def _pack_bits(fields):
    result = 0
    pos = 0
    for value, width in fields:
        _require(0 <= value < (1 << width), 'Packed value out of range')
        result |= value << pos
        pos += width
    return result.to_bytes((pos + 7) // 8, 'little')


def _extension(data, magic, count, gen, widths):
    _require(len(data) >= 22 and data[:4] == magic, 'Missing ' + magic.decode())
    _require(data[4:8] == bytes((1, count, 0, 0)), 'Extension header invalid')
    _require(u16(data, 8) == gen and data[12:14] == b'\0\0', 'Extension generation/reserved invalid')
    size = u16(data, 10)
    _require(22 + size <= len(data), 'Extension length invalid')
    _require(crc(data[:14] + data[16:22+size]) == u16(data, 14), 'Extension CRC invalid')
    kinds, _ = _bits(data[16:22], 2, 24)
    _require(all(k in (0, 1) for k in kinds[:count]) and not any(kinds[count:]), 'Extension kind invalid')
    nbits = sum(w for k, w in zip(kinds, widths) if k)
    _require(size == (nbits + 7)//8, 'Extension bit length invalid')
    payload = data[22:22+size]
    _require(not (int.from_bytes(payload, 'little') >> nbits), 'Nonzero extension padding')
    return kinds[:count], payload, size


def decode_zones(sector):
    """Return (zones, warnings). Blank sector is valid, no zones.
    Invalid membership raises; absent/bad extensions use documented fallback.
    Raw bytes are never mutated.
    """
    sector = bytes(sector)
    _require(len(sector) == ZONE_SIZE, 'Zone sector must be 4096 bytes')
    if sector == b'\xff' * ZONE_SIZE:
        return [], []
    _require(sector[:5] == b'MMZ1\x01', 'Unknown zone format')
    n = sector[5]
    _require(n <= MAX_ZONES and sector[6:8] == b'\0\0' and u16(sector, 8) == MAX_CHANNEL and not any(sector[10:62]), 'Invalid MMZ1 header')
    names = sector[0x200:0x200+16*n]
    maps = sector[0x400:0x400+128*n]
    checksum = u16(sector, 62)
    _require(crc(sector[:62] + names + maps) == checksum, 'MMZ1 CRC invalid')
    zones = []
    for i in range(n):
        rec = names[i*16:(i+1)*16]
        raw = rec[:12].rstrip(b'\0')
        _require(bool(raw) and all(32 <= c <= 126 for c in raw) and not any(rec[14:]), 'Invalid zone name/record')
        bitmap = int.from_bytes(maps[i*128:(i+1)*128], 'little')
        _require(not bitmap >> MAX_CHANNEL, 'Invalid membership bit')
        members = tuple(j+1 for j in range(MAX_CHANNEL) if bitmap & (1 << j))
        _require(len(members) == u16(rec,12) and bool(members), 'Zone member count invalid')
        zones.append(Zone(raw.decode('ascii'), members))
    stream = sector[0x40:0x200] + sector[0x380:0x400]
    warnings = []
    try:
        kinds, data, size = _extension(stream, b'MMZS', n, generation(checksum), [len(z.members) for z in zones])
        pos = 0
        for i, (zone, kind) in enumerate(zip(zones, kinds)):
            if kind:
                flags, pos = _bits(data, 1, len(zone.members), pos)
                scan = tuple(ch for ch, flag in zip(zone.members, flags) if flag)
            else:
                scan = zone.members
            zones[i] = Zone(zone.name, zone.members, scan)
    except ZoneError as exc:
        warnings.append(str(exc) + '; using legacy scan behavior')
        return zones, warnings
    offset = (22+size+15)//16*16
    try:
        widths = [(len(z.members)-1).bit_length() for z in zones]
        kinds, data, _ = _extension(stream[offset:], b'MMZO', n, generation(checksum), [w*len(z.members) for w,z in zip(widths,zones)])
        pos = 0
        result = []
        for zone, kind, width in zip(zones, kinds, widths):
            if kind:
                order, pos = _bits(data, width, len(zone.members), pos)
                _require(sorted(order) == list(range(len(zone.members))), 'Invalid zone permutation')
                members = tuple(zone.members[j] for j in order)
            else:
                members = zone.members
            result.append(Zone(zone.name, members, zone.scan))
        zones = result
    except ZoneError as exc:
        warnings.append(str(exc) + '; using channel-number order')
    return zones, warnings


def _make_extension(magic, n, gen, kinds, payload):
    head = magic + bytes((1,n,0,0)) + p16(gen) + p16(len(payload)) + b'\0\0'
    body = _pack_bits((k,2) for k in list(kinds)+[0]*(MAX_ZONES-n)) + payload
    return head + p16(crc(head+body)) + body


def encode_zones(zones):
    """Encode strict 1.1.0 format. Reject overflow; never silently drop order/scan.
    Input channel numbers are physical slots. This never touches clone channels.
    Legacy scan=None is rejected to avoid silently changing scan semantics.
    """
    zones = list(zones)
    n = len(zones)
    _require(n <= MAX_ZONES, 'More than 24 zones')
    names, maps = bytearray(), bytearray()
    scan_kinds, order_kinds, scan_fields, order_fields = [], [], [], []
    for zone in zones:
        name = zone.name.encode('ascii')
        _require(1 <= len(name) <= 12 and all(32 <= c <= 126 for c in name), 'Zone name must be 1–12 printable ASCII characters')
        members = tuple(zone.members)
        _require(bool(members) and len(set(members)) == len(members) and all(type(ch) is int and 1 <= ch <= MAX_CHANNEL for ch in members), 'Invalid/duplicate channel number')
        _require(zone.scan is not None, 'Legacy scan set must be explicitly specified before encoding')
        scan = tuple(zone.scan)
        _require(len(set(scan)) == len(scan) and set(scan) <= set(members), 'Scan channels must be unique zone members')
        ascending = sorted(members)
        names += name.ljust(12,b'\0') + p16(len(members)) + b'\0\0'
        maps += sum(1 << (ch-1) for ch in members).to_bytes(128,'little')
        kind = int(set(scan) != set(members))
        scan_kinds.append(kind)
        if kind:
            scan_fields.extend((int(ch in scan),1) for ch in ascending)
        kind = int(list(members) != ascending)
        order_kinds.append(kind)
        if kind:
            width = (len(members)-1).bit_length()
            ranks = {ch:i for i,ch in enumerate(ascending)}
            order_fields.extend((ranks[ch],width) for ch in members)
    head = b'MMZ1' + bytes((1,n,0,0)) + p16(MAX_CHANNEL) + bytes(52)
    checksum = crc(head+names+maps)
    gen = generation(checksum)
    scan = _make_extension(b'MMZS', n, gen, scan_kinds, _pack_bits(scan_fields))
    order = _make_extension(b'MMZO', n, gen, order_kinds, _pack_bits(order_fields))
    stream = scan + b'\xff' * ((-len(scan)) % 16) + order
    _require(len(stream) <= 576, 'Zone ordering/scan lists exceed 576-byte extension space; simplify explicitly')
    stream = stream.ljust(576,b'\xff')
    sector = bytearray(b'\xff'*ZONE_SIZE)
    sector[:64] = head+p16(checksum)
    sector[0x200:0x200+len(names)] = names
    sector[0x400:0x400+len(maps)] = maps
    sector[0x40:0x200] = stream[:448]
    sector[0x380:0x400] = stream[448:]
    return bytes(sector)


def validate_report(report):
    """Validate the documented MM9R v2 report before reading custom data."""
    _require(len(report)==64 and report[:5]==b'MM9R\x02', 'No supported MM9PDY MM9R v2 report; use stock driver or update firmware')
    _require(crc(report[:62])==u16(report,62), 'MM9R CRC invalid')
    layout = struct.unpack_from('<II',report,8)
    _require(layout in ((0x95000,0x68000),(0x94000,0x6a000)), 'Unknown MM9PDY flash layout')
    name = report[0x18:0x30].rstrip(b'\0 ').decode('ascii',errors='replace')
    suffix = report[0x30:0x34].rstrip(b'\0 ')
    version = report[0x34:0x39].rstrip(b'\0 ')
    hardware = report[0x39:0x3e].rstrip(b'\0 ')
    _require((suffix,version,hardware) in ((b'NRFB',b'V0.04',b'V1.7'),(b'NRF',b'V0.27',b'V1.7')) or (suffix,version.lower(),hardware.lower()) in ((b'NRFB',b'v0.04',b'v1.7'),(b'NRF',b'v0.27',b'v1.7')), 'Unknown MM9PDY radio identity')
    return name


CHANNEL_END = MAX_CHANNEL * 32
MODES = ('Zones only', 'Channels only', 'Channels and zones',
         'Settings only', 'Zones and settings', 'Channels and settings',
         'Channels, zones and settings', 'Automatic (edited regions)')
AUTO = MODES[-1]
SCOPES = (frozenset('z'), frozenset('c'), frozenset('cz'),
          frozenset('s'), frozenset('zs'), frozenset('cs'), frozenset('czs'))
# Physical clone spans, not contiguous packed addresses. Only these spans
# are allowed by the documented stock/MM9PDY clone protocol.
SETTINGS_REGIONS = ((0x8000, 0x8000, 0x40),
                    (0x9000, 0x8040, 0x40),
                    (0xA000, 0x8080, 0x1C0))


# MM9PDY 1.1.0: verified against sequential physical radio reads.
# Quick Access (0x40) is confirmed on both SK2 assignments. The six
# remaining codes are the documented stock Mini key codes; their use on
# SK2 is inferred from the firmware's identical list and awaits radio tests.
SK2_SHORT = 0x8073
SK2_LONG = 0x8053
WATCH_DUAL = 0x8044
WATCH_SINGLE = 0x8078
KEY_ACTIONS = {0x07: 'FM Radio', 0x1C: 'Scan', 0x1D: 'Search',
               0x2D: 'VOX', 0x08: 'Flashlight', 0x03: 'SOS',
               0x40: 'Quick Access'}
WATCH_MODES = {'Single': (0, 1), 'Dual Watch': (0, 0),
               'Dual Monitor': (1, 0)}


def key_choices(raw, address):
    _require(address in (SK2_SHORT, SK2_LONG), 'Invalid SK2 address')
    choices = dict(KEY_ACTIONS)
    choices[0] = ('Firmware default (Flashlight)' if address == SK2_SHORT
                  else 'Firmware default (Search)')
    if raw not in choices:
        choices[raw] = 'Unchanged (0x%02X)' % raw
    return choices


def watch_choices(raw):
    pair = (raw[WATCH_DUAL], raw[WATCH_SINGLE])
    choices = dict(WATCH_MODES)
    if pair not in choices.values():
        choices['Unchanged (0x%02X, 0x%02X)' % pair] = pair
    return choices, next(name for name, value in choices.items() if value == pair)


def apply_key_action(mmap, address, label):
    choices = key_choices(mmap.get_packed()[address], address)
    _require(label in choices.values(), 'Unknown SK2 function')
    mmap[address] = bytes((next(k for k, v in choices.items() if v == label),))


def apply_watch_mode(mmap, label):
    choices, _ = watch_choices(mmap.get_packed())
    _require(label in choices, 'Unknown watch mode')
    dual, single = choices[label]
    mmap[WATCH_DUAL] = bytes((dual,))
    mmap[WATCH_SINGLE] = bytes((single,))


def settings_bytes(image):
    return image[0x8000:BASE_SIZE]


def allowed_write(address):
    return (address % 64 == 0 and
            (0 <= address < 0x8040 or address == 0x9000 or
             0xA000 <= address < 0xA1C0 or 0xC000 <= address < 0xD000))


def packed_offset(address):
    if 0 <= address < 0x8040:
        return address
    if address == 0x9000:
        return 0x8040
    if 0xA000 <= address < 0xA1C0:
        return 0x8080 + address - 0xA000
    if 0xC000 <= address < 0xD000:
        return BASE_SIZE + address - 0xC000
    raise ZoneError('Unsafe physical address')


# CHIRP image metadata only: never transmitted to the radio. The Android
# bridge reloads a fresh radio instance for every editor operation/upload.
REPORT_KEY = 'mm9pdy_validated_usb_report_v1'
BASELINE_KEY = 'mm9pdy_original_clone_v1'
SCOPE_KEY = 'mm9pdy_upload_scope_v1'


def pack_baseline(raw):
    _require(len(raw) == IMAGE_SIZE, 'Invalid baseline size')
    return {'data': base64.b64encode(zlib.compress(raw, 9)).decode('ascii'),
            'sha256': hashlib.sha256(raw).hexdigest()}


def unpack_baseline(record):
    try:
        encoded = record['data']
        _require(isinstance(encoded, str) and len(encoded) <= 2 * IMAGE_SIZE,
                 'Invalid baseline metadata length')
        dec = zlib.decompressobj()
        raw = dec.decompress(base64.b64decode(encoded, validate=True), IMAGE_SIZE + 1)
        _require(len(raw) == IMAGE_SIZE and dec.eof and not dec.unused_data
                 and not dec.unconsumed_tail, 'Invalid baseline metadata size')
        _require(hashlib.sha256(raw).hexdigest() == record['sha256'],
                 'Baseline checksum mismatch')
        return raw
    except (KeyError, TypeError, ValueError, zlib.error, binascii.Error) as exc:
        raise ZoneError('Invalid MM9PDY baseline metadata; read the radio again') from exc


def android_pipe(pipe):
    return any(c.__name__ in ('AndroidSerialPipe', 'LegacyAndroidSerialPipe')
               for c in type(pipe).__mro__) and hasattr(pipe, '_transport')


def native_ble(pipe):
    # Android's transport flag is authoritative, desktop uses CHIRP platform.
    return bool(getattr(pipe, 'is_direct_ble', False) or
                getattr(pipe, 'is_ble', False) or
                platform.get_platform().is_ble_serial(pipe))


# Stock CHIRP UV5RMini BLE uses 128-byte frames, padding the final
# 64-byte block of each stock clone span with FF. Match that exact stock
# behavior, never borrow bytes from the next packed span. The custom zone
# sector is a full aligned 4 KiB span and requires no padding.
BLE_PAD_TAILS = frozenset((0x8000, 0x9000, 0xA180))


def allowed_ble_write(address, data):
    if address % 128 or len(data) != 128 or not allowed_write(address):
        return False
    if allowed_write(address + 64):
        return True
    return address in BLE_PAD_TAILS and data[64:] == b'\xff' * 64


def plan_ble_write(baseline, desired, scope=AUTO):
    blocks = plan_write(baseline, desired, scope)
    by_address = dict(blocks)
    _require(len(by_address) == len(blocks), 'Duplicate write addresses')
    result = []
    emitted = set()
    # Preserve the USB planner's sector/header-first ordering. Pair physical
    # neighbors, not neighboring entries in the nonsequential zone plan.
    for address, _ in blocks:
        a = address & ~0x7f
        if a in emitted:
            continue
        _require(a in by_address, 'Incomplete BLE write pair at 0x%04X' % a)
        if a + 64 in by_address:
            data = by_address[a] + by_address[a + 64]
        else:
            _require(a in BLE_PAD_TAILS, 'Incomplete BLE write pair at 0x%04X' % a)
            data = by_address[a] + b'\xff' * 64
        _require(allowed_ble_write(a, data), 'BLE write address interlock at 0x%04X' % a)
        result.append((a, data))
        emitted.add(a)
    _require(set(by_address) == {a + i for a, _ in result for i in (0, 64)
                                  if allowed_write(a + i)}, 'BLE plan coverage mismatch')
    return result


def edited_regions(baseline, desired):
    return frozenset(k for k, a, b in (('c', 0, CHANNEL_END),
        ('s', 0x8000, BASE_SIZE), ('z', BASE_SIZE, IMAGE_SIZE))
        if baseline[a:b] != desired[a:b])


def parse_channels(value):
    value = str(value).strip()
    if not value:
        return ()
    try:
        nums = tuple(int(x.strip()) for x in value.split(','))
    except ValueError as exc:
        raise ZoneError('Use comma-separated physical channel numbers') from exc
    _require(len(set(nums)) == len(nums) and all(1 <= n <= MAX_CHANNEL for n in nums),
             'Channel numbers must be unique and in 1–999')
    return nums


def plan_write(baseline, desired, mode=AUTO):
    """Build the complete plan offline. Explicit scopes force a restore.

    The baseline is the image as opened/read, NOT a fresh live radio read.
    Whole erase sectors are written for edited channels; untouched sectors
    are not addressed. No claim is made about unobserved live radio bytes.
    """
    _require(len(baseline) == len(desired) == IMAGE_SIZE, 'Invalid image size')
    _require(mode in MODES, 'Unknown upload scope')
    edited = edited_regions(baseline, desired)
    force = mode != AUTO
    scope = SCOPES[MODES.index(mode)] if force else edited
    _require(edited <= scope, 'Edited regions excluded by upload scope; select Automatic or include all edited regions')
    _require(baseline[CHANNEL_END:0x8000] == desired[CHANNEL_END:0x8000],
             'Unexpected change to reserved bytes outside channel records')
    dz = desired[BASE_SIZE:]
    if 'c' in scope or 'z' in scope:
        zones, warnings = decode_zones(dz)
        _require('z' not in scope or not warnings, 'Refusing invalid or legacy zone extensions')
        _require(all(desired[(n-1)*32:(n-1)*32+4] != b'\xff'*4
                     for z in zones for n in z.members), 'Zone refers to an empty channel in image')
    blocks = []
    if 'c' in scope:
        for start in range(0, 0x8000, 0x1000):
            if force or baseline[start:start+0x1000] != desired[start:start+0x1000]:
                blocks.extend((a, desired[a:a+64]) for a in range(start,start+0x1000,64))
    if 's' in scope:
        for address,offset,length in SETTINGS_REGIONS:
            if force or baseline[offset:offset+length] != desired[offset:offset+length]:
                blocks.extend((address+i,desired[offset+i:offset+i+64]) for i in range(0,length,64))
    if 'z' in scope:
        offsets = [0] + list(range(0x200,0x380,64)) + list(range(0x400,0x1000,64)) + list(range(0x40,0x200,64)) + list(range(0x380,0x400,64))
        blocks.extend((0xc000+a,dz[a:a+64]) for a in offsets)
    _require(all(len(b)==64 and allowed_write(a) for a,b in blocks), 'Write address interlock')
    return blocks


# No CHIRP dependency for offline codec use. CHIRP loads the registered class
# below when this file is installed via its external/community driver mechanism.
try:
    from chirp import chirp_common, directory, errors, memmap, platform
    from chirp.settings import (RadioSettings, RadioSettingGroup, RadioSetting,
                                RadioSettingValueString, RadioSettingValueList)
    from chirp.drivers import baofeng_uv17Pro as upstream
    from chirp.drivers import baofeng_common as bfc
except ModuleNotFoundError as exc:
    if exc.name != 'chirp':
        raise
    upstream = None


def _install_desktop_zone_refresh():
    """Refresh CHIRP's cached editors only for this community driver.

    No wx import on Android/headless CHIRP. The desktop editor API does not
    provide a driver-level settings invalidation notification, so wrap its
    existing selected() method when the wx modules are already loaded.
    """
    settings_module = sys.modules.get('chirp.wxui.settingsedit')
    bank_module = sys.modules.get('chirp.wxui.bankedit')
    settings_class = getattr(settings_module, 'ChirpSettingsEdit', None)
    bank_class = getattr(bank_module, 'ChirpBankEdit', None)
    if settings_class is not None and not getattr(settings_class.selected, '_mm9_zone_refresh', False):
        original = settings_class.selected

        @wraps(original)
        def settings_selected(editor, *args, **kwargs):
            radio = getattr(editor, '_radio', None)
            cached = getattr(editor, '_settings', None)
            if (getattr(radio, '_mm9_zone_tab_sync', False)
                    and getattr(editor, '_initialized', False)
                    and cached is not None
                    and getattr(cached, '_mm9_bank_epoch', None) != radio._mm9_bank_epoch):
                editor.refresh()
            return original(editor, *args, **kwargs)

        settings_selected._mm9_zone_refresh = True
        settings_class.selected = settings_selected
    if bank_class is not None and not getattr(bank_class.selected, '_mm9_zone_refresh', False):
        original_bank = bank_class.selected

        @wraps(original_bank)
        def bank_selected(editor, *args, **kwargs):
            radio = getattr(editor, '_radio', None)
            if getattr(radio, '_mm9_zone_tab_sync', False):
                for col, definition in enumerate(editor._col_defs):
                    editor._grid.SetColLabelValue(col, definition.label)
            return original_bank(editor, *args, **kwargs)

        bank_selected._mm9_zone_refresh = True
        bank_class.selected = bank_selected


if upstream is not None:
    class MM9PDYBank(chirp_common.NamedBank):
        def get_name(self):
            return self._model._radio._slots[self._index].name

        def set_name(self, name):
            radio = self._model._radio
            slots = list(radio._slots)
            old = slots[self._index]
            slots[self._index] = Zone(str(name), old.members, old.scan)
            radio._commit_bank_slots(slots)

    class MM9PDYBankModel(chirp_common.MTOBankModel):
        def __init__(self, radio):
            super().__init__(radio, name='Zones')

        def get_num_mappings(self):
            return MAX_ZONES

        def get_mappings(self):
            return [MM9PDYBank(self,i,'Zone %02d' % (i+1)) for i in range(MAX_ZONES)]

        def get_mapping_memories(self, mapping):
            return [self._radio.get_memory(ch) for ch in self._radio._slots[mapping.get_index()].members]

        def get_memory_mappings(self, memory):
            return [bank for bank in self.get_mappings() if memory.number in self._radio._slots[bank.get_index()].members]

        def add_memory_to_mapping(self, memory, mapping):
            if memory.empty:
                raise errors.RadioError('Cannot add an empty memory to a zone')
            radio = self._radio
            slots = list(radio._slots)
            i = mapping.get_index()
            z = slots[i]
            if memory.number not in z.members:
                scan = None if z.scan is None else tuple(z.scan)+(memory.number,)
                slots[i] = Zone(z.name, z.members+(memory.number,),scan)
                radio._commit_bank_slots(slots)

        def remove_memory_from_mapping(self, memory, mapping):
            radio = self._radio
            slots = list(radio._slots)
            i = mapping.get_index()
            z = slots[i]
            if memory.number not in z.members:
                raise errors.RadioError('Memory is not in this zone')
            members = tuple(n for n in z.members if n != memory.number)
            scan = None if z.scan is None and members else tuple(n for n in (z.scan or ()) if n != memory.number)
            slots[i] = Zone(z.name,members,scan)
            radio._commit_bank_slots(slots)

    @directory.register
    class PCUV5RMiniMM9PDY(upstream.UV5RMini):
        """Optional PC community driver — guarded USB write beta."""
        VENDOR = 'Baofeng'
        MODEL = 'PC-UV-5R Mini MM9PDY'
        VARIANT = ''
        MEM_TOTAL = IMAGE_SIZE
        _mem_size = IMAGE_SIZE
        _memsize = IMAGE_SIZE
        MEM_STARTS = [0x0000,0x9000,0xA000,0xC000]
        MEM_SIZES = [0x8040,0x40,0x1C0,0x1000]
        # Replace the parent Mini SK1 enum with correct Mini wire codes.
        _has_skey1_short = False
        _mm9_zone_tab_sync = True
        _mm9_bank_epoch = 0
        _zones = ()
        _zone_warnings = ()
        _upload_scope = AUTO
        _slots = tuple(Zone("Zone %02d" % (i+1),(),()) for i in range(MAX_ZONES))

        @classmethod
        def match_model(cls, filedata, filename):
            # No accidental matching of stock images, even if same lineage.
            return False

        def get_features(self):
            rf = super().get_features()
            rf.has_bank = True
            rf.has_bank_names = True
            rf.has_bank_index = False
            # Expose inherited radio settings and custom zone controls.
            rf.has_settings = True
            return rf

        def get_bank_model(self):
            _install_desktop_zone_refresh()
            return MM9PDYBankModel(self)

        def process_mmap(self):
            raw = self._mmap.get_packed()
            if len(raw) != IMAGE_SIZE:
                raise errors.RadioError('MM9PDY image must contain 0x9240 bytes (clone + zones)')
            try:
                self._zones, self._zone_warnings = decode_zones(raw[BASE_SIZE:])
            except ZoneError as exc:
                raise errors.RadioError(str(exc)) from exc
            self._slots = tuple(self._zones) + tuple(Zone('Zone %02d' % (i+1),(),()) for i in range(len(self._zones),MAX_ZONES))
            metadata = getattr(self, '_metadata', {})
            record = metadata.get(BASELINE_KEY)
            try:
                self._baseline = unpack_baseline(record) if record is not None else raw
            except ZoneError as exc:
                raise errors.RadioError(str(exc)) from exc
            self._baseline_persisted = record is not None
            self._upload_scope = metadata.get(SCOPE_KEY, AUTO)
            if self._upload_scope not in MODES:
                self._upload_scope = AUTO
            self._mm9_bank_epoch += 1
            for warning in self._zone_warnings:
                LOG.warning('MM9PDY: %s',warning)
            super().process_mmap()

        def _commit_bank_slots(self, slots):
            before = self._slots
            self._commit_slots(slots)
            if self._slots != before:
                self._mm9_bank_epoch += 1

        def _commit_slots(self, slots):
            try:
                active = [z for z in slots if z.members]
                for z in slots:
                    _require(1 <= len(z.name) <= 12 and all(32 <= ord(c) <= 126 for c in z.name), 'Zone name must be 1–12 printable ASCII characters')
                # Renaming an empty placeholder is an in-session change only.
                sector = (self._mmap.get_packed()[BASE_SIZE:] if active == list(self._zones)
                          else encode_zones(active))
                _require(all(not self.get_memory(n).empty for z in active for n in z.members), 'Zone refers to an empty memory')
                self._mmap[BASE_SIZE] = sector
                self._slots = tuple(slots)
                self._zones = active
            except (ValueError, UnicodeError) as exc:
                raise errors.RadioError(str(exc)) from exc

        def get_settings(self):
            _install_desktop_zone_refresh()
            control = RadioSettingGroup('mm9control','MM9PDY Upload')
            setting = RadioSetting('mm9scope','Upload scope',RadioSettingValueList(list(MODES),current_index=MODES.index(self._upload_scope)))
            setting.set_doc('Automatic uploads only regions edited since the original read (or desktop image open). Explicit scopes restore entire selected regions from this image, even without edits. No pre-write clone read: changes on the radio since this image was read may be overwritten in written sectors. Settings includes VFO, general settings and DTMF.')
            control.append(setting)
            inherited = list(super().get_settings())
            # Stock CHIRP key callback maps several Mini labels to the wrong
            # wire code. Use the documented Mini SK1 codes, and preserve
            # any unknown/custom code until its meaning is confirmed.
            basic = next((g for g in inherited if g.get_name() == 'basic'), None)
            if basic is None:
                basic = RadioSettingGroup('basic', 'Basic Settings')
                inherited.insert(0, basic)
            if basic is not None:
                raw = self._mmap.get_packed()[0x8040+0x32]
                codes = {0x07:'FM Radio',0x1C:'Scan',0x1D:'Search',
                         0x2D:'VOX',0x08:'Flashlight',0x03:'SOS'}
                if raw not in codes:
                    codes[raw] = 'Unchanged (0x%02X)' % raw
                labels = list(codes.values())
                sk = RadioSetting('settings.key1short','PRESS SK1 (Side Button Tap)',
                    RadioSettingValueList(labels,current_index=labels.index(codes[raw])))
                def apply_sk1(setting, mapping=codes):
                    code = next(k for k,v in mapping.items() if v==str(setting.value))
                    self._mmap[0x8040+0x32] = bytes((code,))
                sk.set_apply_callback(apply_sk1)
                basic.append(sk)
            # Replace stock Dual Watch (two modes) with the firmware's
            # three-mode control, rather than leaving conflicting settings.
            # Remove any inherited SK2 settings so they cannot write the
            # wrong offsets or overwrite custom assignments.
            def remove_conflicts(group):
                for item in list(group):
                    if isinstance(item, RadioSetting):
                        if item.get_name() in ('settings.dualstandby',
                                'settings.singlewatch', 'settings.key2short',
                                'settings.key2long'):
                            del group[item]
                    else:
                        remove_conflicts(item)
            for group in inherited:
                remove_conflicts(group)
            # Quick Access is a live radio menu, not a codeplug settings group.
            # Keep all persistent button assignments and Watch Mode together.
            raw_image = self._mmap.get_packed()
            for address, name, title in (
                    (SK2_SHORT, 'mm9sk2short', 'PRESS SK2 (Center Button Tap)'),
                    (SK2_LONG, 'mm9sk2long', 'HOLD SK2 (Center Button Hold)')):
                codes = key_choices(raw_image[address], address)
                labels = list(codes.values())
                item = RadioSetting(name, title, RadioSettingValueList(
                    labels, current_index=labels.index(codes[raw_image[address]])))
                item.set_doc('Assign the blue center button. Quick Access opens Scan, Light, Monitor and Watch Mode. Six original key codes are inherited from the documented Mini key list; physical SK2 validation is pending.')
                def apply_action(setting, addr=address):
                    apply_key_action(self._mmap, addr, str(setting.value))
                item.set_apply_callback(apply_action)
                basic.append(item)
            watch, current = watch_choices(raw_image)
            labels = list(watch)
            item = RadioSetting('mm9watch', 'Watch Mode', RadioSettingValueList(
                labels, current_index=labels.index(current)))
            item.set_doc('Radio Set > Watch Mode (also available in Quick Access). Single: one active side. Dual Watch: receive on active side. Dual Monitor: receive on both sides in turn.')
            def apply_watch(setting):
                apply_watch_mode(self._mmap, str(setting.value))
            item.set_apply_callback(apply_watch)
            basic.append(item)
            groups = inherited + [control]
            for i,z in enumerate(self._slots):
                group = RadioSettingGroup('mm9zone%d' % i,'Zone %02d' % (i+1))
                group.append(RadioSetting('z%d_name' % i,'Name',RadioSettingValueString(1,12,z.name,autopad=False)))
                group.append(RadioSetting('z%d_members' % i,'Members in display order (comma-separated)',RadioSettingValueString(0,4096,','.join(map(str,z.members)),autopad=False)))
                scan = ('LEGACY' if z.scan is None else 'ALL' if set(z.scan)==set(z.members) else ','.join(map(str,z.scan)))
                group.append(RadioSetting('z%d_scan' % i,'Scan members (ALL, or comma-separated)',RadioSettingValueString(0,4096,scan,autopad=False)))
                groups.append(group)
            result = RadioSettings(*groups)
            result._mm9_bank_epoch = self._mm9_bank_epoch
            return result

        def set_settings(self, settings):
            def flatten(group):
                for item in group:
                    if isinstance(item,RadioSetting):
                        yield item
                    else:
                        yield from flatten(item)
            changed = [item for item in flatten(settings) if item.changed()]
            custom_names = {'mm9scope'} | {'z%d_%s' % (i,field)
                for i in range(MAX_ZONES) for field in ('name','members','scan')}
            fields = {item.get_name():str(item.value) for item in changed
                      if item.get_name() in custom_names}
            normal = [item for item in changed if item.get_name() not in custom_names]
            # wx copies the settings tree (including old dirty flags) before
            # applying it. Never allow a cached zone edit to undo a newer
            # Banks-tab edit, even if tab refresh has not happened yet.
            if (any(name.startswith('z') for name in fields)
                    and getattr(settings, '_mm9_bank_epoch', self._mm9_bank_epoch)
                    != self._mm9_bank_epoch):
                raise errors.RadioError('Zones changed in Banks. Reopen Settings before editing zones.')
            # Parent set_settings recursively dispatches to self.set_settings;
            # a flat list avoids recursion into our custom settings handler.
            old_bytes = self._mmap.get_packed()
            old_slots, old_zones, old_scope = self._slots, self._zones, self._upload_scope
            slots = list(self._slots)
            try:
                for i,z in enumerate(slots):
                    prefix = 'z%d_' % i
                    name = fields.get(prefix+'name',z.name)
                    members = parse_channels(fields[prefix+'members']) if prefix+'members' in fields else z.members
                    scan_text = fields.get(prefix+'scan')
                    if scan_text is not None:
                        scan = members if scan_text.strip().upper()=='ALL' else None if scan_text.strip().upper()=='LEGACY' else parse_channels(scan_text)
                    elif z.scan is not None and set(z.scan)==set(z.members):
                        scan = members
                    else:
                        scan = None if z.scan is None else tuple(n for n in z.scan if n in members)
                    slots[i] = Zone(name,members,scan if members else ())
                scope = fields.get('mm9scope',self._upload_scope)
                _require(scope in MODES,'Invalid upload scope')
                if slots != list(self._slots):
                    self._commit_slots(slots)
                if normal:
                    super().set_settings(normal)
                    new = self._mmap.get_packed()
                    _require(new[:0x8000] == old_bytes[:0x8000], 'Settings attempted to modify channel memory')
                self._upload_scope = scope
                if hasattr(self, '_metadata'):
                    self._metadata[SCOPE_KEY] = scope
            except Exception as exc:
                # Restore the same map object so bitwise settings callbacks
                # remain bound to the correct storage.
                self._mmap[0] = old_bytes
                self._slots, self._zones, self._upload_scope = old_slots, old_zones, old_scope
                if isinstance(exc, errors.RadioError):
                    raise
                raise errors.RadioError(str(exc)) from exc

        def set_memory(self, memory):
            # Never implicitly move or delete memberships. Remove the memory
            # from its zones before deleting its channel record.
            if memory.empty and any(memory.number in z.members for z in self._slots):
                raise errors.RadioError('Remove this channel from its zones before deleting it')
            raw = self._get_raw_memory(memory.number)
            if memory.empty or self.get_memory(memory.number).empty:
                return super().set_memory(memory)
            # Existing channels: retain reserved bytes instead of resetting the record.
            raw.name = memory.name.ljust(self.get_features().valid_name_length,'\xff')
            self.set_memory_common(memory,raw)

        def _read_mm_block(self, address, diagnostic=False):
            bfc._rawsend(self,self._make_read_frame(address,0x40))
            reply = bfc._rawrecv(self,0x44)
            if len(reply) != 0x44 or reply[:4] != struct.pack('>BHB',0x52,address,0x40):
                raise errors.RadioError('Invalid read reply at 0x%04X: len=%d header=%s' % (address,len(reply),reply[:4].hex()))
            payload = reply[4:]
            decoded = upstream._crypt(self._encrsym,payload)
            if diagnostic:
                self._mm9_probe = '0x%04X wire=%s decoded=%s' % (address,payload[:8].hex(),decoded[:8].hex())
                LOG.info('MM9PDY probe: %s',self._mm9_probe)
            return decoded

        def sync_in(self):
            # Read-only fallback when the firmware-report signature is absent:
            # require a complete, nonblank CRC-validated MMZ1/MMZS/MMZO table.
            # This establishes zone-data compatibility, not running firmware
            # identity. BLE writes use the standard Mini handshake
            # and the existing image; USB uses previously stored MM9R evidence.
            upstream._do_ident(self)
            try:
                verified_usb_report = None
                report = self._read_mm_block(0xEFC0, diagnostic=True)
                report_probe = self._mm9_probe
                zone_data = None
                if report[:5] == b'MM9R\x02' or report[:4] == b'MM9R':
                    name = validate_report(report)
                    LOG.info('MM9PDY report: %s',name)
                    if not native_ble(self.pipe) and name.lower() in ('v0.04-nrfb-1.1.0','v0.27-nrf-1.1.0'):
                        verified_usb_report = bytes(report).hex()
                else:
                    # A valid frame with an unexpected signature can occur
                    # if a transport does not expose the report address.
                    # Never accept a blank zone sector as identification.
                    try:
                        header = self._read_mm_block(0xC000, diagnostic=True)
                        zone_probe = self._mm9_probe
                        _require(header[:5] == b'MMZ1\x01', 'No MMZ1 zone header')
                        zone_data = header + b''.join(self._read_mm_block(a) for a in range(0xC040,0xD000,0x40))
                        zones, warnings = decode_zones(zone_data)
                        _require(not warnings, 'Zone extensions failed validation: '+ '; '.join(warnings))
                    except (ZoneError, errors.RadioError) as exc:
                        raise errors.RadioError('MM9PDY read probe failed: report [%s]; zone [%s]; %s' % (report_probe, getattr(self,'_mm9_probe','unavailable'),exc)) from exc
                    LOG.warning('MM9PDY firmware report unavailable [%s]; validated zone table [%s], %d zones. Firmware identity unverified; USB custom-region WRITE requires stored MM9R evidence.',report_probe,zone_probe,len(zones))
                status = chirp_common.Status()
                status.max = IMAGE_SIZE//0x40
                status.cur = 0
                status.msg = 'Reading MM9PDY channels and zones'
                data = bytearray()
                for start,size in zip(self.MEM_STARTS,self.MEM_SIZES):
                    if start == 0xC000 and zone_data is not None:
                        data.extend(zone_data)
                        status.cur += len(zone_data)//0x40
                        self.status_fn(status)
                        continue
                    for address in range(start,start+size,0x40):
                        data.extend(self._read_mm_block(address))
                        status.cur += 1
                        self.status_fn(status)
                self._mmap = memmap.MemoryMapBytes(bytes(data))
                if not hasattr(self, '_metadata'):
                    self._metadata = {}
                self._metadata.pop(REPORT_KEY, None)
                if verified_usb_report is not None:
                    self._metadata[REPORT_KEY] = verified_usb_report
                self._metadata[BASELINE_KEY] = pack_baseline(bytes(data))
                self._metadata[SCOPE_KEY] = AUTO
                self.process_mmap()
            except ZoneError as exc:
                raise errors.RadioError(str(exc)) from exc

        def _write_block(self, address, data):
            if len(data)!=64 or not allowed_write(address):
                raise errors.RadioError('Blocked unsafe write address')
            payload = upstream._crypt(self._encrsym,data)
            bfc._rawsend(self,self._make_frame(b'W',address,64,payload))
            if bfc._rawrecv(self,1)!=b'\x06':
                raise errors.RadioError('Bad write ACK at 0x%04X; stop and inspect radio' % address)

        def _sync_out_ble(self):
            # No radio READ commands before or after upload. Use the existing
            # image baseline from either transport. The standard Mini
            # write protocol does not require the USB-only MM9R report.
            wrote = False
            try:
                _require(getattr(self, '_baseline_persisted', False),
                         'Original image baseline missing; open a fresh clone from either transport')
                desired = self._mmap.get_packed()
                # Offline validation only; no radio probe and no USB dependency.
                _require(self._baseline[BASE_SIZE:BASE_SIZE+5] == b'MMZ1\x01',
                         'Original image has no MM9PDY zone table')
                _, warnings = decode_zones(self._baseline[BASE_SIZE:])
                _require(not warnings, 'Original zone table failed validation')
                plan = plan_ble_write(self._baseline, desired, self._upload_scope)
                _require(bool(plan), 'MM9PDY: no edited memory regions; no upload sent')
                status = chirp_common.Status()
                status.cur = 0
                status.max = len(plan)
                status.msg = 'BLE WRITE: handshake (no pre-read)'
                self.status_fn(status)
                upstream._do_ident(self)
                status.msg = 'BLE WRITE: channels/settings/zones (128-byte frames)'
                for address, data in plan:
                    _require(allowed_ble_write(address, data), 'Blocked unsafe BLE write frame')
                    wrote = True
                    payload = upstream._crypt(self._encrsym, data)
                    bfc._rawsend(self, self._make_frame(b'W', address, 128, payload))
                    if bfc._rawrecv(self, 1) != b'\x06':
                        raise errors.RadioError('Bad BLE write ACK at 0x%04X' % address)
                    status.cur += 1
                    self.status_fn(status)
                status.msg = 'BLE upload ACKed; allow radio to reboot'
                self.status_fn(status)
                # Do not send another command or force readback. Leave baseline
                # intact until the operator performs an independent READ.
                LOG.info('MM9PDY BLE upload ACKed: %d frames; no automatic readback',len(plan))
            except Exception as exc:
                if wrote:
                    raise errors.RadioError('BLE upload may be partial; allow reboot and manually read before retrying. '+str(exc)) from exc
                if isinstance(exc, errors.RadioError):
                    raise
                raise errors.RadioError(str(exc)) from exc

        def sync_out(self):
            if native_ble(self.pipe):
                return self._sync_out_ble()
            desired = self._mmap.get_packed()
            wrote = False
            try:
                is_android = android_pipe(self.pipe)
                if is_android and not self._baseline_persisted:
                    raise errors.RadioError('MM9PDY: original image baseline missing; upload not sent')
                plan = plan_write(self._baseline,desired,self._upload_scope)
                LOG.info('MM9PDY upload plan: %d frames; scope=%s; persisted baseline=%s',len(plan),self._upload_scope,self._baseline_persisted)
                if not plan:
                    if is_android:
                        raise errors.RadioError('MM9PDY: no edited memory regions; no upload sent')
                    LOG.info('MM9PDY: no changes; no writes sent')
                    return
                # Validate custom-region firmware evidence from the image only.
                # The handshake identifies the live radio family, not its firmware.
                if any(a >= 0x8000 for a, _ in plan):
                    report_hex = getattr(self, '_metadata', {}).get(REPORT_KEY, '')
                    _require(isinstance(report_hex, str) and len(report_hex) == 128,
                             'USB settings/zone upload requires stored MM9R evidence from an existing USB image; no automatic read performed')
                    name = validate_report(bytes.fromhex(report_hex))
                    _require(name.lower() in ('v0.04-nrfb-1.1.0','v0.27-nrf-1.1.0'), 'Write beta requires exact MM9PDY 1.1.0 build in image metadata')
                upstream._do_ident(self)
                status = chirp_common.Status()
                status.max = len(plan)
                status.cur = 0
                status.msg = 'Writing MM9PDY: '+self._upload_scope
                for address,data in plan:
                    wrote = True
                    self._write_block(address,data)
                    status.cur += 1
                    self.status_fn(status)
                # Final ACK is the transfer result. Do not probe or re-enter
                # programming mode: allow the radio to reboot on its own.
                status.msg = 'USB upload ACKed; allow radio to reboot'
                self.status_fn(status)
                # Preserve the original baseline until an independent READ.
                LOG.info('MM9PDY USB upload ACKed: %d frames; no automatic readback',len(plan))
            except Exception as exc:
                if wrote:
                    raise errors.RadioError('Upload may be partial; do not blindly retry. Read radio and compare backup. '+str(exc)) from exc
                if isinstance(exc,errors.RadioError):
                    raise
                raise errors.RadioError(str(exc)) from exc

        def upload_function(self):
            return self.sync_out()


if __name__ == '__main__':
    import argparse
    import json
    import zipfile
    from pathlib import Path
    parser = argparse.ArgumentParser(description='Offline MM9PDY zone codec (no radio access)')
    sub = parser.add_subparsers(dest='cmd',required=True)
    show = sub.add_parser('inspect',help='Decode Studio ZIP or raw 4096-byte sector')
    show.add_argument('input')
    enc = sub.add_parser('encode',help='Encode a JSON zone list into a standalone sector')
    enc.add_argument('input')
    enc.add_argument('output')
    args = parser.parse_args()
    if args.cmd == 'inspect':
        if zipfile.is_zipfile(args.input):
            with zipfile.ZipFile(args.input) as archive:
                sector = archive.read('regions/zones.bin')
        else:
            sector = Path(args.input).read_bytes()
        zones,warnings = decode_zones(sector)
        print(json.dumps({'zones':[{'name':z.name,'members':z.members,'scan':z.scan} for z in zones], 'warnings':warnings},indent=2))
    else:
        raw = json.loads(Path(args.input).read_text(encoding='utf-8'))
        if isinstance(raw,dict):
            raw = raw['zones']
        zones = [Zone(z['name'],tuple(z['members']),None if z.get('scan') is None else tuple(z['scan'])) for z in raw]
        # Exclusive creation prevents overwriting input/previous backup.
        with open(args.output,'xb') as dest:
            dest.write(encode_zones(zones))
