# Quansheng UV-K5 driver (c) 2023 Jacek Lipkowski <sq5bpf@lipkowski.org>
#
# based on template.py Copyright 2012 Dan Smith <dsmith@danplanet.com>
#
#
# This is a preliminary version of a driver for the UV-K5
# It is based on my reverse engineering effort described here:
# https://github.com/sq5bpf/uvk5-reverse-engineering
#
# Warning: this driver is experimental, it may brick your radio,
# eat your lunch and mess up your configuration.
#
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Adapted partially to IJV firmware v2.9 by Julian Lilov (LZ1JDL)
# https://www.universirius.com/en_gb/preppers/quansheng-uv-k5-manuale-del-firmware-ijv/#Firmware-IJV
#
# Adapted to IJV Firmware  by Francesco IK8JHL 
# FIX:  QRA , Beacon/CQ CAll Message, Selettive , TX Enable, PTTID, Squelch A/B, Band TX, Band A/B TX , Singol Band enable,  Satcom , Upconverter etc etc
# eliminatte funzioni non attive nel FW IJV
# aggiunta impostazione Tono custom , Hz = Valore /10
#
# Modificata struttura per renderlo compatibile con la versione 3.00 by IJV
# jhl> fix vari, inserimento frequenze con punto decimale , eliminate E , aggiunto screen A/B .., DTMF Contact ,etc etc
# jhl> adapted to IJV-vX3 999 Channel

# IJV Version : 55
#JHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHL
IJV_VAR = 0 # 0 = BANCO 0 / 1 = BANCO 1 E 2
#JHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHL
from re import A
import struct
import logging

from chirp import chirp_common, directory, bitwise, memmap, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueInteger, RadioSettingValueString, \
    RadioSettings, RadioSettingSubGroup

LOG = logging.getLogger(__name__)

# Show the obfuscated version of commands. Not needed normally, but
# might be useful for someone who is debugging a similar radio
DEBUG_SHOW_OBFUSCATED_COMMANDS = False

# Show the memory being written/received. Not needed normally, because
# this is the same information as in the packet hexdumps, but
# might be useful for someone debugging some obscure memory issue
DEBUG_SHOW_MEMORY_ACTIONS = True

if IJV_VAR == 0 :   
    MEM_1 = """

    // -------------------0x300
    #seekto 0x300;
    struct 
    {
        char name[8];
    } list_name[16];  
     
    """    
else :             
    MEM_1 = """

    // -------------------0x9D00
    #seekto 0x9D00;
    struct 
    {
        char name[8];
    } list_name[16];  
     
    """
    
MEM_2 = """
    #seekto 0x2000;

    struct 
    {
      // ---------------rec 1 + 2 
      char name[10];
      u8 code_sel0:4,
         code_sel1:4;
      u8 code_sel2:4,
         code_sel3:4;
      u8 code_sel4:4,
         code_sel5:4;
      u8 code_sel6:4,
         code_sel7:4;
      u8 code_sel8:4,
         code_sel9:4;
      u8 group:4,
         band:4;

      // ---------------rec 3  
      ul32 freq;
      ul32 offset;

      // ---------------rec 4
      u8 rxcode;
      u8 txcode;

      u8 tx_codetype:4,
         rx_codetype:4;

      u8 txlock:1,
         writeprot:1,
         enablescan:1,
         modulation:3,
         shift:2;

      u8 busylock:1,
         txpower:2,
         bw:4,
         reverse:1;

      u8 libero:3,
         compander:2,
         agcmode:3;
      
      u8 squelch:4,
         step:4;

      u8 scrambler:1, 
         ptt_id:4,
         digcode:3;     

    } channel[999];
"""


MEM_FORMAT = MEM_1 + MEM_2 
# //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\ @ BANCO 0 //\\//\\//\\//\\//\\//\\//\\//\\//\\
if IJV_VAR == 0 :

    PROG_SIZE_U = 0x0300 # inizio User setting
    PROG_SIZE = 0x0380  # fine user setting Setting 
    
    CHAN_MAX = 999  # 999 Memorie
    MEM_SIZE = 0xA000  # Grandezza massima della memoria 
    PROG_SIZEM = 0xA000 # Grandezza massima Eprom scrittura Memoria 
    START_MEM = 0x2000 # Indirizzo di partenza scrittura memorie 
    
# //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\ Impostazione 200 canali //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\
else :  
# //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\  @ BANCO 1 e 2 //\\//\\//\\//\\//\\//\\//\\//\\//\\

    PROG_SIZE_U = 0x9D00 # inizio User setting
    PROG_SIZE = 0x0080  # Grandezza massima Eprom scrittura Setting 
    
    CHAN_MAX = 999  # 999 Memorie
    MEM_SIZE = 0xA000  # Grandezza massima della memoria 
    PROG_SIZEM = 0xA000 # Grandezza massima Eprom scrittura Memoria 
    START_MEM = 0x2000 # Indirizzo di partenza scrittura memorie 
    
# //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\ Impostazione 999 canali //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\


MEM_BLOCK = 0x80  # largest block of memory that we can reliably write

# OFFSET
OFFSET_NONE = 0b00
OFFSET_PLUS = 0b01
OFFSET_MINUS = 0b10


# TX POWER

POWER_LOW = 0b00
POWER_MEDIUM = 0b01
POWER_HIGH = 0b10

TXPOWER_LIST = ["Low","Mid","High"]

# BANDWIDTH
BANDWIDTH_WIDE = 0b00
BANDWIDTH_NARROW = 0b01
BANDWIDTH_NARROW_MINUS = 0b10
BANDWIDTH_WIDE_PLUS = 0b11

BANDWIDTH_LIST = ["W 26k",
                  "W 23k",
                  "W 20k",
                  "W 17k",
                  "W 14k",
                  "W.12k",
                  "N 10k",
                  "N. 9k",
                  "U  7k",
                  "U  6k"]

MODULATION_LIST = ["FM","AM","USB","CW","WFM","DIG"]

# dtmf_flags
PTTID_LIST = ["OFF", "CALL ID", "SEL CALL", "CODE BEGIN", "CODE END", "CODE BEG+END",  
              "ROGER Single", "ROGER 2Tones", "MDC 1200", "Apollo Quindar" ]

# power
UVK5_POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=1.00),
                     chirp_common.PowerLevel("Med",  watts=2.50),
                     chirp_common.PowerLevel("High", watts=5.00)]

#Digital Code
DIGITAL_CODE_LIST = ["OFF","DTMF","ZVEI1","ZVEI2","CCIR-1","CCIR-1F","USER"]

# squelch list
SQUELCH_LIST = ["Squelch 0","Squelch 1","Squelch 2","Squelch 3","Squelch 4","Squelch 5","Squelch 6","Squelch 7","Squelch 8","Squelch 9","NO RX"]

# compander
COMPANDER_LIST = ["OFF", "TX", "RX", "RX/TX"]

# enable scan
SKIP_VALUES = ["", "S", "P"]

# steps    0     1     2     3     4     5    6     7      8     9     10     11     12     13      14      15
STEPS = [0.01, 0.05, 0.10, 0.50, 1.00, 2.50, 5.00, 6.25, 8.33, 9.00, 10.00, 12.50, 20.00, 25.00, 50.00, 100.00]

STEP_LIST = ["   10 Hz",
             "   50 Hz",
             "  100 Hz",
             "  500 Hz",
             "   1 kHz",
             " 2.5 kHz",
             "   5 kHz",
             "6.25 kHz",
             "8.33 kHz",
             "   9 kHz",
             "  10 kHz",
             "12.5 kHz",
             "  20 kHz",
             "  25 kHz",
             "  50 kHz",
             " 100 kHz"]

AGC_MODE = ["AUTO","MAN","FAST","NORM","SLOW"]

# ctcss/dcs codes
TMODES = ["", "Tone", "DTCS", "DTCS"]
TONE_NONE = 0
TONE_CTCSS = 1
TONE_DCS = 2
TONE_RDCS = 3


CTCSS_TONES = [
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4,
    88.5, 91.5, 94.8, 97.4, 100.0, 103.5, 107.2, 110.9,
    114.8, 118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2,
    151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
    177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5,
    203.5, 206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8,
    250.3, 254.1, 
]

# lifted from ft4.py
DTCS_CODES = [
    23,  25,  26,  31,  32,  36,  43,  47,  51,  53,  54,
    65,  71,  72,  73,  74,  114, 115, 116, 122, 125, 131,
    132, 134, 143, 145, 152, 155, 156, 162, 165, 172, 174,
    205, 212, 223, 225, 226, 243, 244, 245, 246, 251, 252,
    255, 261, 263, 265, 266, 271, 274, 306, 311, 315, 325,
    331, 332, 343, 346, 351, 356, 364, 365, 371, 411, 412,
    413, 423, 431, 432, 445, 446, 452, 454, 455, 462, 464,
    465, 466, 503, 506, 516, 523, 526, 532, 546, 565, 606,
    612, 624, 627, 631, 632, 654, 662, 664, 703, 712, 723,
    731, 732, 734, 743, 754
]

# bands supported by the UV-K5
BANDS = {
        0: [13.0, 107.9999],
        1: [108.0, 136.9999],
        2: [137.0, 173.9990],
        3: [174.0, 349.9999],
        4: [350.0, 399.9999],
        5: [400.0, 469.9999],
        6: [470.0, 1299.9999]
}

SPECIALS = {
        # "VFO A1(15-108)": 200,
        # "VFO B1(15-108)": 201,
        # "VFO A2(108-137)": 202,
        # "VFO B2(108-137)": 203,
        # "VFO A3(137-174)": 204,
        # "VFO B3(137-174)": 205,
        # "VFO A4(174-350)": 206,
        # "VFO B4(174-350)": 207,
        # "VFO A5(350-400)": 208,
        # "VFO B5(350-400)": 209,
        # "VFO A6(400-470)": 210,
        # "VFO B6(400-470)": 211,
        # "VFO A7(470-1300)": 212,
        # "VFO B7(470-1300)": 213
}

DTMF_CHARS = "0123456789ABCDEF*# "
DTMF_CHARS_ID = "0123456789ABCDabcdef#* "

DTMF_CHARS_UPDOWN = "0123456789ABCDEFabcdef#* "
DTMF_CODE_CHARS = "ABCDEF*# "
DTMF_DECODE_RESPONSE_LIST = ["None", "Ring", "Reply", "Both"]

GROUP_LIST = ["No Group",
              "Group 1",
              "Group 2",
              "Group 3",
              "Group 4",
              "Group 5",
              "Group 6",
              "Group 7",
              "Group 8",
              "Group 9",
              "Group 10",
              "Group 11",
              "Group 12",
              "Group 13",
              "Group 14",
              "Group 15"]

EMPTY_MEM = [0,0,0,0,0,0,0,0,0,0,0xEE,0xEE,0xEE,0xEE,0xEE,0,
             0,0,0,0,0,0,0,0,0,0,0   ,0   ,0   ,0   ,0   ,0]

def min_max_def(value, min_val, max_val, default):
    """returns value if in bounds or default otherwise"""
    if min_val is not None and value < min_val:
        return default
    if max_val is not None and value > max_val:
        return default
    return value


#--------------------------------------------------------------------------------
# nibble to ascii
def hexasc(data):
    res = data 
    if res<=9:
        return chr(res+48)
    elif data == 0xA:
        return "A"
    elif data == 0xB:
        return "B"
    elif data == 0xC:
        return "C"
    elif data == 0xD:
        return "D"    
    elif data == 0xF:
        return "F"
    else:
        return " "

#--------------------------------------------------------------------------------
# nibble to ascii
def ascdec(data):

    if data == "0":
        return 0
    elif data == "1":
        return 1
    elif data == "2":
        return 2
    elif data == "3":
        return 3
    elif data == "4":
        return 4
    elif data == "5":
        return 5
    elif data == "6":
        return 6
    elif data == "7":
        return 7
    elif data == "8":
        return 8
    elif data == "9":
        return 9
    elif data == "A":
        return 10
    elif data == "B":
        return 11
    elif data == "C":
        return 12
    elif data == "D":
        return 13
    elif data == "F":
        return 15
    else:
        return 14


#--------------------------------------------------------------------------------
# the communication is obfuscated using this fine mechanism
def xorarr(data: bytes):
    tbl = [22, 108, 20, 230, 46, 145, 13, 64, 33, 53, 213, 64, 19, 3, 233, 128]
    x = b""
    r = 0
    for byte in data:
        x += bytes([byte ^ tbl[r]])
        r = (r+1) % len(tbl)
    return x

#--------------------------------------------------------------------------------
# if this crc was used for communication to AND from the radio, then it
# would be a measure to increase reliability.
# but it's only used towards the radio, so it's for further obfuscation
def calculate_crc16_xmodem(data: bytes):
    poly = 0x1021
    crc = 0x0
    for byte in data:
        crc = crc ^ (byte << 8)
        for i in range(8):
            crc = crc << 1
            if (crc & 0x10000):
                crc = (crc ^ poly) & 0xFFFF
    return crc & 0xFFFF

#--------------------------------------------------------------------------------
def _send_command(serport, data: bytes):
    """Send a command to UV-K5 radio"""
    LOG.debug("Sending command (unobfuscated) len=0x%4.4x:\n%s" %
              (len(data), util.hexprint(data)))

    crc = calculate_crc16_xmodem(data)
    data2 = data + struct.pack("<H", crc)

    command = struct.pack(">HBB", 0xabcd, len(data), 0) + \
        xorarr(data2) + \
        struct.pack(">H", 0xdcba)
    if DEBUG_SHOW_OBFUSCATED_COMMANDS:
        LOG.debug("Sending command (obfuscated):\n%s" % util.hexprint(command))
    try:
        result = serport.write(command)
    except Exception:
        raise errors.RadioError("Error writing data to radio")
    return result

#--------------------------------------------------------------------------------
def _receive_reply(serport):
    header = serport.read(4)
    if len(header) != 4:
        LOG.warning("Header short read: [%s] len=%i" %
                    (util.hexprint(header), len(header)))
        raise errors.RadioError("Header short read")
    if header[0] != 0xAB or header[1] != 0xCD or header[3] != 0x00:
        LOG.warning("Bad response header: %s len=%i" %
                    (util.hexprint(header), len(header)))
        raise errors.RadioError("Bad response header")

    cmd = serport.read(int(header[2]))
    if len(cmd) != int(header[2]):
        LOG.warning("Body short read: [%s] len=%i" %
                    (util.hexprint(cmd), len(cmd)))
        raise errors.RadioError("Command body short read")

    footer = serport.read(4)

    if len(footer) != 4:
        LOG.warning("Footer short read: [%s] len=%i" %
                    (util.hexprint(footer), len(footer)))
        raise errors.RadioError("Footer short read")

    if footer[2] != 0xDC or footer[3] != 0xBA:
        LOG.debug(
                "Reply before bad response footer (obfuscated)"
                "len=0x%4.4x:\n%s" % (len(cmd), util.hexprint(cmd)))
        LOG.warning("Bad response footer: %s len=%i" %
                    (util.hexprint(footer), len(footer)))
        raise errors.RadioError("Bad response footer")

    if DEBUG_SHOW_OBFUSCATED_COMMANDS:
        LOG.debug("Received reply (obfuscated) len=0x%4.4x:\n%s" %
                  (len(cmd), util.hexprint(cmd)))

    cmd2 = xorarr(cmd)

    LOG.debug("Received reply (unobfuscated) len=0x%4.4x:\n%s" %
              (len(cmd2), util.hexprint(cmd2)))

    return cmd2

#--------------------------------------------------------------------------------
def _getstring(data: bytes, begin, maxlen):
    tmplen = min(maxlen+1, len(data))
    s = [data[i] for i in range(begin, tmplen)]
    for key, val in enumerate(s):
        if val < ord(' ') or val > ord('~'):
            break
    return ''.join(chr(x) for x in s[0:key])

#--------------------------------------------------------------------------------
def _sayhello(serport):
    hellopacket = b"\x14\x05\x04\x00\x6a\x39\x57\x64"

    tries = 5
    while True:
        LOG.debug("Sending hello packet")
        _send_command(serport, hellopacket)
        o = _receive_reply(serport)
        if (o):
            break
        tries -= 1
        if tries == 0:
            LOG.warning("Failed to initialise radio")
            raise errors.RadioError("Failed to initialize radio")
    firmware = _getstring(o, 4, 16)
    LOG.info("Found firmware: %s" % firmware)
    return firmware

#--------------------------------------------------------------------------------
def _readmem(serport, offset, length):
    LOG.debug("Sending readmem offset=0x%4.4x len=0x%4.4x" % (offset, length))

    readmem = b"\x1b\x05\x08\x00" + \
        struct.pack("<HBB", offset, length, 0) + \
        b"\x6a\x39\x57\x64"
    _send_command(serport, readmem)
    o = _receive_reply(serport)
    if DEBUG_SHOW_MEMORY_ACTIONS:
        LOG.debug("readmem Received data len=0x%4.4x:\n%s" %
                  (len(o), util.hexprint(o)))
    return o[8:]

#--------------------------------------------------------------------------------
def _writemem(serport, data, offset):
    LOG.debug("Sending writemem offset=0x%4.4x len=0x%4.4x" %
              (offset, len(data)))

    if DEBUG_SHOW_MEMORY_ACTIONS:
        LOG.debug("writemem sent data offset=0x%4.4x len=0x%4.4x:\n%s" %
                  (offset, len(data), util.hexprint(data)))

    dlen = len(data)
    writemem = b"\x1d\x05" + \
        struct.pack("<BBHBB", dlen+8, 0, offset, dlen, 1) + \
        b"\x6a\x39\x57\x64"+data

    _send_command(serport, writemem)
    o = _receive_reply(serport)

    LOG.debug("writemem Received data: %s len=%i" % (util.hexprint(o), len(o)))

    if (o[0] == 0x1e
            and
            o[4] == (offset & 0xff)
            and
            o[5] == (offset >> 8) & 0xff):
        return True
    else:
        LOG.warning("Bad data from writemem")
        raise errors.RadioError("Bad response to writemem")

#--------------------------------------------------------------------------------
def _resetradio(serport):
    resetpacket = b"\xdd\x05\x00\x00"
    _send_command(serport, resetpacket)

#------------------------------Lettura Eprom--------------------------------------------------
def do_download(radio):
    serport = radio.pipe
    serport.timeout = 0.5
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE
    status.msg = "Downloading from radio"
    radio.status_fn(status)

    eeprom = b""
    f = _sayhello(serport)
    if f:
        radio.FIRMWARE_VERSION = f
    else:
        raise errors.RadioError('Unable to determine firmware version')

    addr = 0
    while addr < MEM_SIZE:
        o = _readmem(serport, addr, MEM_BLOCK)
        status.cur = addr
        radio.status_fn(status)

        if o and len(o) == MEM_BLOCK:
            eeprom += o
            addr += MEM_BLOCK
        else:
            raise errors.RadioError("Memory download incomplete")

    return memmap.MemoryMapBytes(eeprom)

#-------------------------------Scrittura Eprom-------------------------------------------------
def do_upload(radio):
    serport = radio.pipe
    serport.timeout = 0.5
    status = chirp_common.Status()
    status.cur = 0
    status.max = PROG_SIZE
    status.msg = "Uploading Group Setting to radio"
    radio.status_fn(status)

    f = _sayhello(serport)
    if f:
        radio.FIRMWARE_VERSION = f
    else:
        return False

#---------------Scrittura Group List
    addr = PROG_SIZE_U
    while addr < PROG_SIZE:
        o = radio.get_mmap()[addr:addr+MEM_BLOCK]
        _writemem(serport, o, addr)
        status.cur = addr
        radio.status_fn(status)
        if o:
            addr += MEM_BLOCK
        else:
            raise errors.RadioError("Upload Group Setting incomplete")
            
#----------------Scrittura Memorie            
    status.msg = "Uploading Memory to radio"   
    status.max = PROG_SIZEM
    status.cur = 0
    addr = START_MEM
    
    while addr < PROG_SIZEM:
        o = radio.get_mmap()[addr:addr+MEM_BLOCK]
        _writemem(serport, o, addr)
        status.cur = addr
        radio.status_fn(status)
        if o:
            addr += MEM_BLOCK
        else:
            raise errors.RadioError("Memory upload incomplete")
    status.msg = "Uploaded  OK"

    _resetradio(serport)

    return True

#--------------------------------------------------------------------------------
def _find_band(hz):
    mhz = hz/1000000.0

    B = BANDS

    for a in B:
        if mhz >= B[a][0] and mhz <= B[a][1]:
            return a

    return False

################################################################################################################################

################################################################################################################################

@directory.register
class UVK5Radio(chirp_common.CloneModeRadio):
    """Quansheng UV-K5"""
    VENDOR = "Quansheng"
    MODEL = "UV-K5"
    if IJV_VAR == 0 :
        VARIANT = "IJV_V3" # @variant v3
    else:    
        VARIANT = "IJV_VX3" # @variant vX3
    BAUD_RATE = 38400
    NEEDS_COMPAT_SERIAL = False
    FIRMWARE_VERSION = "300"
    _expanded_limits = True

#--------------------------------------------------------------------------------
    # def get_prompts(x=None):
        # rp = chirp_common.RadioPrompts()
        # rp.experimental = _(
            # 'This is an experimental driver for the Quansheng UV-K5. '
            # 'It may harm your radio, or worse. Use at your own risk.\n\n'
            # 'Before attempting to do any changes please download '
            # 'the memory image from the radio with chirp '
            # 'and keep it. This can be later used to recover the '
            # 'original settings. \n\n'
            # 'some details are not yet implemented')
        # rp.pre_download = _(
            # "1. Turn radio on.\n"
            # "2. Connect cable to mic/spkr connector.\n"
            # "3. Make sure connector is firmly connected.\n"
            # "4. Click OK to download image from device.\n\n"
            # "It will may not work if you turn on the radio "
            # "with the cable already attached\n")
        # rp.pre_upload = _(
            # "1. Turn radio on.\n"
            # "2. Connect cable to mic/spkr connector.\n"
            # "3. Make sure connector is firmly connected.\n"
            # "4. Click OK to upload the image to device.\n\n"
            # "It will may not work if you turn on the radio "
            # "with the cable already attached")
        # return rp

#--------------------------------------------------------------------------------    # Return information about this radio's features, including
    # how many memories it has, what bands it supports, etc
    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_rx_dtcs = True
        rf.has_ctone = True
        rf.has_settings = True
        rf.has_comment = False

        rf.valid_dtcs_codes = DTCS_CODES
        rf.valid_name_length = 10
        rf.valid_power_levels = UVK5_POWER_LEVELS
        rf.valid_special_chans = list(SPECIALS.keys())
        rf.valid_duplexes = ["", "-", "+", "off"]
        rf.valid_tuning_steps = STEPS
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone","->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_modes = ["FM","AM","USB","CW","WFM","DIG"]
        rf.valid_skips = ["", "S"]
        rf._expanded_limits = True

        # This radio supports memories 1-200 / 1-999
        rf.memory_bounds = (1, CHAN_MAX)

        rf.valid_bands = []
        for a in BANDS:
            rf.valid_bands.append(
                    (int(BANDS[a][0]*1000000),
                     int(BANDS[a][1]*1000000)))
        return rf
#--------------------------------------------------------------------------------
    # Do a download of the radio from the serial port
    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()
#--------------------------------------------------------------------------------
    # Do an upload of the radio to the serial port
    def sync_out(self):
        do_upload(self)
#--------------------------------------------------------------------------------
    # Convert the raw byte array into a memory object structure
    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
#-------------------------------------------------------------------------------- 
    # Return a raw representation of the memory object, which
    # is very helpful for development
    def get_raw_memory(self, number):
        return repr(self._memobj.channel[number-1])
#-------------------------------------------------------------------------------- VALIDAZIONE MEMORIA
    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)

        if mem.duplex == 'off':
            return msgs

        # find tx frequency
        if mem.duplex == '-':
            txfreq = mem.freq - mem.offset
        elif mem.duplex == '+':
            txfreq = mem.freq + mem.offset
        else:
            txfreq = mem.freq

        # find band
        band = _find_band(txfreq)
        if band is False:
            msg = "Transmit frequency %.4f MHz is not supported by this radio" % (txfreq/1000000.0)
            msgs.append(chirp_common.ValidationError(msg))

        band = _find_band(mem.freq)
        if band is False:
            msg = "The frequency %.4f MHz is not supported by this radio" % (mem.freq/1000000.0)
            msgs.append(chirp_common.ValidationError(msg))

        return msgs
#-------------------------------------------------------------------------------- IMPOSTA TONI
    def _set_tone(self, mem, _mem):
        ((txmode, txtone, txpol),
         (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)

        if txmode == "Tone":
            txtoval = CTCSS_TONES.index(txtone)
            txmoval = 0b01
        elif txmode == "DTCS":
            txmoval = txpol == "R" and 0b11 or 0b10
            txtoval = DTCS_CODES.index(txtone)
        else:
            txmoval = 0
            txtoval = 0

        if rxmode == "Tone":
            rxtoval = CTCSS_TONES.index(rxtone)
            rxmoval = 0b01
        elif rxmode == "DTCS":
            rxmoval = rxpol == "R" and 0b11 or 0b10
            rxtoval = DTCS_CODES.index(rxtone)
        else:
            rxmoval = 0
            rxtoval = 0

        _mem.rx_codetype = rxmoval
        _mem.tx_codetype = txmoval
        _mem.rxcode = rxtoval
        _mem.txcode = txtoval

#-------------------------------------------------------------------------------- LEGGI TONI
    def _get_tone(self, mem, _mem):
        rxtype = _mem.rx_codetype
        txtype = _mem.tx_codetype

        rx_tmode = TMODES[rxtype]
        tx_tmode = TMODES[txtype]

        rx_tone = tx_tone = None

        if tx_tmode == "Tone":
            if _mem.txcode < len(CTCSS_TONES):
                tx_tone = CTCSS_TONES[_mem.txcode]
            else:
                tx_tone = 0
                tx_tmode = ""
        elif tx_tmode == "DTCS":
            if _mem.txcode < len(DTCS_CODES):
                tx_tone = DTCS_CODES[_mem.txcode]
            else:
                tx_tone = 0
                tx_tmode = ""

        if rx_tmode == "Tone":
            if _mem.rxcode < len(CTCSS_TONES):
                rx_tone = CTCSS_TONES[_mem.rxcode]
            else:
                rx_tone = 0
                rx_tmode = ""
        elif rx_tmode == "DTCS":
            if _mem.rxcode < len(DTCS_CODES):
                rx_tone = DTCS_CODES[_mem.rxcode]
            else:
                rx_tone = 0
                rx_tmode = ""

        tx_pol = txtype == 0x03 and "R" or "N"
        rx_pol = rxtype == 0x03 and "R" or "N"

        chirp_common.split_tone_decode(mem, (tx_tmode, tx_tone, tx_pol),(rx_tmode, rx_tone, rx_pol))


################################################################################################################################
#                                                                                                 L E T T U R A   M E M O R I E
################################################################################################################################

#--------------------------------------------------------------------------------
    # Extract a high-level memory object from the low-level memory map
    # This is called to populate a memory in the UI
    def get_memory(self, number2):

        _mem = self._memobj
        for i in range(0, 16):
            GROUP_LIST[i] = str(_mem.list_name[i].name).strip("\x00\xff")
            if GROUP_LIST[i].startswith(" "):
                GROUP_LIST[i] = "----- "


        mem = chirp_common.Memory()

        if isinstance(number2, str):
            number = SPECIALS[number2]
            mem.extd_number = number2
        else:
            number = number2 - 1

        mem.number = number + 1

        _mem = self._memobj.channel[number]

        tmpcomment = ""

        is_empty = False
        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if (_mem.freq == 0xffffffff) or (_mem.freq == 0) or (_mem.band == 0xF):
            is_empty = True

        if is_empty:
            mem.empty = True
            # set some sane defaults:
            mem.power = UVK5_POWER_LEVELS[2]
            mem.extra = RadioSettingGroup("Extra", "extra")

            rs = RadioSetting("bandwidth", "Bandwidth", RadioSettingValueList(BANDWIDTH_LIST, BANDWIDTH_LIST[0]))
            mem.extra.append(rs)

            rs = RadioSetting("frev", "FreqRev", RadioSettingValueBoolean(False))
            mem.extra.append(rs)

            rs = RadioSetting("pttid", "PTTID", RadioSettingValueList(PTTID_LIST, PTTID_LIST[0]))
            mem.extra.append(rs)

            #rs = RadioSetting("dtmfdecode", _("DTMF decode"), RadioSettingValueBoolean(False))
            #mem.extra.append(rs)

            rs = RadioSetting("agcmode", _("AGC mode"), RadioSettingValueList(AGC_MODE, AGC_MODE[0]))
            mem.extra.append(rs)

            rs = RadioSetting("compander", _("Compander"), RadioSettingValueList(COMPANDER_LIST, COMPANDER_LIST[0]))
            mem.extra.append(rs)            
            
            rs = RadioSetting("scrambler", _("Scrambler"), RadioSettingValueBoolean(False))
            mem.extra.append(rs)

            rs = RadioSetting("squelch", _("Squelch"), RadioSettingValueList(SQUELCH_LIST, SQUELCH_LIST[1]))
            mem.extra.append(rs)

            rs = RadioSetting("writeprot", _("Write Protect"),  RadioSettingValueBoolean(False))
            mem.extra.append(rs)

            rs = RadioSetting("txlock", _("TX Lock"),  RadioSettingValueBoolean(False))
            mem.extra.append(rs)

            rs = RadioSetting("group", "Group", RadioSettingValueList(GROUP_LIST, GROUP_LIST[0]))
            mem.extra.append(rs)

            rs = RadioSetting("busylock", "Busy Lock", RadioSettingValueBoolean(False))
            mem.extra.append(rs)

            # actually the step and duplex are overwritten by chirp based on
            # bandplan. they are here to document sane defaults for IARU r1
            # mem.tuning_step = 25.0
            # mem.duplex = ""

            return mem

        if number > (CHAN_MAX-1):
             mem.immutable = ["name", "scanlists"]
        else:
             _mem2 = self._memobj.channel[number]
             for char in _mem2.name:
                 if str(char) == "\xFF" or str(char) == "\x00":
                     break
                 mem.name += str(char)
                 
             tag = mem.name.strip()
             mem.name = tag

        # Convert your low-level frequency to Hertz
        mem.freq = int(_mem.freq)*10
        mem.offset = int(_mem.offset)*10

        if (mem.offset == 0):
            mem.duplex = ''
        else:
            if _mem.shift == OFFSET_MINUS:
                if _mem.freq == _mem.offset:
                    # fake tx disable by setting tx to 0 MHz
                    mem.duplex = 'off'
                    mem.offset = 0
                else:
                    mem.duplex = '-'
            elif _mem.shift == OFFSET_PLUS:
                mem.duplex = '+'
            else:
                mem.duplex = ''

        # tone data
        self._get_tone(mem, _mem)

        # mode
        mem.mode = MODULATION_LIST[_mem.modulation]

        # tuning step
        tstep = _mem.step
        if tstep < len(STEPS):
            mem.tuning_step = STEPS[tstep]
        else:
            mem.tuning_step = 0.02

        # enable scan
        mem.skip = SKIP_VALUES[_mem.enablescan]

        # power
        if _mem.txpower == POWER_HIGH:
            mem.power = UVK5_POWER_LEVELS[2]
        elif _mem.txpower == POWER_MEDIUM:
            mem.power = UVK5_POWER_LEVELS[1]
        else:
            mem.power = UVK5_POWER_LEVELS[0]

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if (_mem.freq == 0xffffffff) or (_mem.freq == 0):
            mem.empty = True
        else:
            mem.empty = False

        mem.extra = RadioSettingGroup("Extra", "extra")

         # bandwidth
        bwidth = _mem.bw
        if bwidth > len(BANDWIDTH_LIST):
            bwidth = 0
        rs = RadioSetting("bandwidth", "Bandwidth", RadioSettingValueList(BANDWIDTH_LIST, BANDWIDTH_LIST[bwidth]))
        mem.extra.append(rs)
        tmpcomment += "bandwidth:"+BANDWIDTH_LIST[bwidth]+" "

         # Group List
        group = _mem.group
        if group > len(GROUP_LIST):
            group = 0
        rs = RadioSetting("group", "Group", RadioSettingValueList(GROUP_LIST, GROUP_LIST[group]))
        mem.extra.append(rs)
        tmpcomment += GROUP_LIST[group]+" "

        # Frequency reverse - whatever that means, don't see it in the manual
        is_frev = bool(_mem.reverse > 0)
        rs = RadioSetting("frev", "FreqRev", RadioSettingValueBoolean(is_frev))
        mem.extra.append(rs)
        tmpcomment += "FreqReverse:"+(is_frev and "ON" or "OFF")+" "

        # PTTID
        pttid = _mem.ptt_id
        if pttid > len(PTTID_LIST):
            pttid = 0
        rs = RadioSetting("pttid", "PTTID", RadioSettingValueList(PTTID_LIST, PTTID_LIST[pttid]))
        mem.extra.append(rs)
        tmpcomment += "PTTid:"+PTTID_LIST[pttid]+" "

        # CODICI SELETTIVE

        codesel = hexasc(_mem.code_sel0) + \
                  hexasc(_mem.code_sel1) + \
                  hexasc(_mem.code_sel2) + \
                  hexasc(_mem.code_sel3) + \
                  hexasc(_mem.code_sel4) + \
                  hexasc(_mem.code_sel5) + \
                  hexasc(_mem.code_sel6) + \
                  hexasc(_mem.code_sel7) + \
                  hexasc(_mem.code_sel8) + \
                  hexasc(_mem.code_sel9)

        rs = RadioSetting("codesel", "Code PTTID", RadioSettingValueString(0, 10, codesel))
        mem.extra.append(rs)
        tmpcomment += "PTTid Codes:"+codesel+" "

        # DIGITAL CODE
        if _mem.digcode < len(DIGITAL_CODE_LIST):
            enc = _mem.digcode
        else:
            enc = 0
            
        rs = RadioSetting("DIGCode", _("DIGCode"), RadioSettingValueList(DIGITAL_CODE_LIST, DIGITAL_CODE_LIST[enc]))
        mem.extra.append(rs)
        tmpcomment += "DIGCode:"+DIGITAL_CODE_LIST[enc]+" "

        # agc mode
        if _mem.agcmode < len(AGC_MODE):
            enc = _mem.agcmode
        else:
            enc = 0

        rs = RadioSetting("agcmode", _("AGC mode"), RadioSettingValueList(AGC_MODE, AGC_MODE[enc]))
        mem.extra.append(rs)
        tmpcomment += "AGC Mode:"+AGC_MODE[enc]+" "

        # compander
        comp = _mem.compander
        rs = RadioSetting("compander", _("Compander"), RadioSettingValueList(COMPANDER_LIST, COMPANDER_LIST[comp]))
        mem.extra.append(rs)
        tmpcomment += "Compander:"+COMPANDER_LIST[comp]+" "
        
        #scrambler
        scr = bool(_mem.scrambler > 0)
        rs = RadioSetting("scrambler", _("Scrambler"),  RadioSettingValueBoolean(scr))
        mem.extra.append(rs)
        tmpcomment += "Scrambler:"+(scr and "ON" or "OFF")+" "

        # Squelch
        if _mem.squelch < len(SQUELCH_LIST):
            sql = _mem.squelch 
        else:
            sql = 1

        rs = RadioSetting("squelch", _("Squelch"), RadioSettingValueList(SQUELCH_LIST, SQUELCH_LIST[sql]))
        mem.extra.append(rs)
        tmpcomment += SQUELCH_LIST[sql]+" "

        # BusyLock
        bl = bool(_mem.busylock > 0)
        rs = RadioSetting("busylock", "Busy Lock", RadioSettingValueBoolean(bl))
        mem.extra.append(rs)
        tmpcomment += "Busy Lock:"+(bl and "ON" or "OFF")+" "
        
        # Write Protect
        wp = bool(_mem.writeprot > 0)
        rs = RadioSetting("writeprot", _("Write Protect"),  RadioSettingValueBoolean(wp))
        mem.extra.append(rs)
        tmpcomment += "Write Protect:"+(wp and "ON" or "OFF")+" "

        # TX Lock
        wp = bool(_mem.txlock > 0)
        rs = RadioSetting("txlock", _("TX Lock"),  RadioSettingValueBoolean(wp))
        mem.extra.append(rs)
        tmpcomment += "TX Lock:"+(wp and "ON" or "OFF")+" "

        return mem


################################################################################################################################
#                                                                                         S A L V A T A G G I O   M E M O R I E
################################################################################################################################

#--------------------------------------------------------------------------------
    # Store details about a high-level memory to the memory map
    # This is called when a user edits a memory in the UI
    def set_memory(self, mem):
        number = mem.number-1

        if number > CHAN_MAX:
            return mem

        # Get a low-level memory object mapped to the image
        _mem = self._memobj.channel[number]

        # this was an empty memory
        if _mem.get_raw(asbytes=False)[0] == "\xff":
           _mem.set_raw("\x00" * 32)
           _mem.code_sel0 = 14
           _mem.code_sel1 = 14
           _mem.code_sel2 = 14
           _mem.code_sel3 = 14
           _mem.code_sel4 = 14
           _mem.code_sel5 = 14
           _mem.code_sel6 = 14
           _mem.code_sel7 = 14
           _mem.code_sel8 = 14
           _mem.code_sel9 = 14

        # find band
        _mem.band = _find_band(mem.freq)

        # mode

        _mem.modulation = MODULATION_LIST.index(mem.mode)

        # frequency/offset
        _mem.freq = mem.freq/10
        _mem.offset = mem.offset/10

        if mem.duplex == "":
            _mem.offset = 0
            _mem.shift = 0
        elif mem.duplex == '-':
            _mem.shift = OFFSET_MINUS
        elif mem.duplex == '+':
            _mem.shift = OFFSET_PLUS
        elif mem.duplex == 'off':
            #
            _mem.shift = OFFSET_MINUS
            _mem.offset = _mem.freq

        # name
        tag = mem.name.ljust(10)
        _mem.name = tag

        # tone data
        self._set_tone(mem, _mem)

        # step
        _mem.step = STEPS.index(mem.tuning_step)

        # tx power
        if str(mem.power) == str(UVK5_POWER_LEVELS[2]):
            _mem.txpower = POWER_HIGH
        elif str(mem.power) == str(UVK5_POWER_LEVELS[1]):
            _mem.txpower = POWER_MEDIUM
        else:
            _mem.txpower = POWER_LOW

        # enable scan
        _mem.enablescan = SKIP_VALUES.index(mem.skip)

        #extra
        for setting in mem.extra:
            sname  = setting.get_name()
            svalue = setting.value.get_value()

            if sname == "bandwidth":
                _mem.bw = BANDWIDTH_LIST.index(svalue)

            if sname == "pttid":
                _mem.ptt_id = PTTID_LIST.index(svalue)

            if sname == "frev":
                _mem.reverse = svalue and 1 or 0

            if sname == "DIGCode":
                _mem.digcode = DIGITAL_CODE_LIST.index(svalue)

            if sname == "agcmode":
                _mem.agcmode = AGC_MODE.index(svalue)

            if sname == "compander":
                _mem.compander = COMPANDER_LIST.index(svalue)            
                
            if sname == "scrambler":
                _mem.scrambler = svalue and 1 or 0

            if sname == "group":
                _mem.group = GROUP_LIST.index(svalue)

            if sname == "squelch":
                _mem.squelch = SQUELCH_LIST.index(svalue)

            if sname == "busylock":
                _mem.busylock = svalue and 1 or 0

            if sname == "writeprot":
                _mem.writeprot = svalue and 1 or 0

            if sname == "txlock":
                _mem.txlock = svalue and 1 or 0

            if sname == "codesel":
                _mem.code_sel0 = ascdec(svalue[0])
                _mem.code_sel1 = ascdec(svalue[1])
                _mem.code_sel2 = ascdec(svalue[2])
                _mem.code_sel3 = ascdec(svalue[3])
                _mem.code_sel4 = ascdec(svalue[4])
                _mem.code_sel5 = ascdec(svalue[5])
                _mem.code_sel6 = ascdec(svalue[6])
                _mem.code_sel7 = ascdec(svalue[7])
                _mem.code_sel8 = ascdec(svalue[8])
                _mem.code_sel9 = ascdec(svalue[9])

        if _mem.freq == 0:
           _mem.set_raw("\xFF" * 32)
           _mem.code_sel0 = 14
           _mem.code_sel1 = 14
           _mem.code_sel2 = 14
           _mem.code_sel3 = 14
           _mem.code_sel4 = 14
           _mem.code_sel5 = 14
           _mem.code_sel6 = 14
           _mem.code_sel7 = 14
           _mem.code_sel8 = 14
           _mem.code_sel9 = 14

        return mem


################################################################################################################################
#                                                                                               L E T T U R A   S E T T I N G S
################################################################################################################################

#--------------------------------------------------------------------------------
    def get_settings(self):
        _mem = self._memobj
        lstn  = RadioSettingGroup("lstn",   "Memory Group")
        roinfo = RadioSettingGroup("roinfo", _("Driver information"))

        # top = RadioSettings( basic, vfoch, agc, keya, dtmf, utone, dtmfc, lstn, preset, expert, calibration, roinfo )
        # top = RadioSettings( basic, vfoch, agc, keya, dtmf, dtmfc, lstn, preset, expert, calibration, roinfo )
        top = RadioSettings( lstn, roinfo )
#--------------------------------------------------------------------------------
        # helper function
        def append_label(radio_setting, label, descr=""):
            if not hasattr(append_label, 'idx'):
                append_label.idx = 0

            val = RadioSettingValueString(len(descr), len(descr), descr)
            val.set_mutable(False)
            rs = RadioSetting("label" + str(append_label.idx), label, val)
            append_label.idx += 1
            radio_setting.append(rs)

        #********************************************************************************** SEZIONE GRUPPI O LISTE

        # LIST NAME
        append_label(lstn, "_" * 30 + " Memory Group LIST NAME " + "_" * 274, "_" * 300)
        # # S-LIST
        # tmpmax = _mem.ch_list
        # if tmpmax >= len(GROUP_LIST):
        #     tmpmax = GROUP_LIST.index("none")
        # rs = RadioSetting("ch_list","Memory Group in use",RadioSettingValueList(GROUP_LIST,GROUP_LIST[tmpmax]))
        # lstn.append(rs)  

        val = RadioSettingValueString(0, 80,"List Name")
        val.set_mutable(False)
        rs = RadioSetting("list_descr1", "Memory Group ", val)
        lstn.append(rs)

        for i in range(0, 16):
            varlist = "List Name_"+str(i)
            vardescrl = "Memory Group "+str(i)+" "

            cntnl = str(_mem.list_name[i].name).strip("\x20\x00\xff")

            val = RadioSettingValueString(0, 8, cntnl)
            rs = RadioSetting(varlist, vardescrl, val)
            lstn.append(rs)


        #********************************************************************************** SEZIONE INFO
        # readonly info
        # Firmware
        if self.FIRMWARE_VERSION == "":
            firmware = "To get the firmware version please download"
            "the image from the radio first"
        else:
            firmware = self.FIRMWARE_VERSION

        val = RadioSettingValueString(0, 128, firmware)
        val.set_mutable(False)
        rs = RadioSetting("fw_ver", "Firmware Version", val)
        roinfo.append(rs)

        # No limits version for hacked firmware
        val = RadioSettingValueBoolean(self._expanded_limits)
        rs = RadioSetting("nolimits", "Limits disabled for modified firmware",val)
        rs.set_warning(_(
            'This should only be enabled if you are using modified firmware '
            'that supports wider frequency coverage. Enabling this will cause '
            'CHIRP not to enforce OEM restrictions and may lead to undefined '
            'or unregulated behavior. Use at your own risk!'),
            safe_value=False)
        roinfo.append(rs)
        
        # Mem Speed
        #tmpmemspeed = _mem.mem_speed - 6
        #if tmpmemspeed >= len(MEMSPEED_LIST) or tmpmemspeed <= 0:
        #    tmpmemspeed = 0
        #rs = RadioSetting("mem_speed","SPI Memory Speed", RadioSettingValueList(MEMSPEED_LIST,MEMSPEED_LIST[tmpmemspeed]))
        #roinfo.append(rs)

        return top



################################################################################################################################
#                                                                                        S A L V A T A G G I O  S E T T I N G S
################################################################################################################################

#--------------------------------------------------------------------------------
    def set_settings(self, settings):

        _mem = self._memobj

        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue

            #--------------------------------------------------- LIST
            # list name
            if element.get_name() == "List Name_0":
                _mem.list_name[0].name = element.value
            if element.get_name() == "List Name_1":
                _mem.list_name[1].name = element.value
            if element.get_name() == "List Name_2":
                _mem.list_name[2].name = element.value
            if element.get_name() == "List Name_3":
                _mem.list_name[3].name = element.value
            if element.get_name() == "List Name_4":
                _mem.list_name[4].name = element.value
            if element.get_name() == "List Name_5":
                _mem.list_name[5].name = element.value
            if element.get_name() == "List Name_6":
                _mem.list_name[6].name = element.value
            if element.get_name() == "List Name_7":
                _mem.list_name[7].name = element.value
            if element.get_name() == "List Name_8":
                _mem.list_name[8].name = element.value
            if element.get_name() == "List Name_9":
                _mem.list_name[9].name = element.value
            if element.get_name() == "List Name_10":
                _mem.list_name[10].name = element.value
            if element.get_name() == "List Name_11":
                _mem.list_name[11].name = element.value
            if element.get_name() == "List Name_12":
                _mem.list_name[12].name = element.value
            if element.get_name() == "List Name_13":
                _mem.list_name[13].name = element.value
            if element.get_name() == "List Name_14":
                _mem.list_name[14].name = element.value
            if element.get_name() == "List Name_15":
                _mem.list_name[15].name = element.value

             # S-LIST
            if element.get_name() == "ch_list":
                _mem.ch_list = GROUP_LIST.index(str(element.value))
