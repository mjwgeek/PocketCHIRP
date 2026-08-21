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

# IJV Version : 60
#JHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHLJHL
IJV_VAR = 0 #@variant 0 per versione V3 ; 1 per versione VX3 
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
MEM_1 = """
// -------------------0x0000
ul16 call_channel;
u8 max_talk_time;
u8 tx_dev;
u8 key_lock;
u8 vox_switch;
u8 vox_level;
u8 mic_gain;
// -------------------0x0008
u8 beep_control;
u8 channel_display_mode;
u8 no_used2;
u8 battery_save;
u8 afc;
u8 backlight_auto_mode;
u8 tail_note_elimination;
u8 vfo_lock;
// -------------------0x0010
u8 flock;
u8 scan_resume_mode;
u8 auto_keypad_lock;
u8 power_on_dispmode;
u8 vfomode;
u8 no_used4;
u8 beacon;

u8 no_used5:1,
   bl_mode:2,
   micbar:1,
   bat_text:1,
   dtmf_live:2,
   tx_enable:1;
   
// -------------------0x0018
struct
{
    u8 val;
} agc[7];

u8 no_used6:2,
   upconv:2,
   satcom:1,
   signal_meter:1,
   no_used7:1,
   savedirect:1;
   
// -------------------0x0020
u8 alarm_mode;
u8 reminding_of_end_talk;
u8 repeater_tail_elimination;
u8 bands_tx;
u8 back_type;
u8 mem_speed;
u8 no_used10;
u8 no_used11;
// -------------------0x0028
struct {
    u8 side_tone;
    char separate_code;
    char group_call_code;
    u8 decode_response;
    u8 auto_reset_time;
    u8 preload_time;
    u8 first_code_persist_time;
    u8 hash_persist_time;
    u8 code_persist_time;
    u8 code_interval_time;
} dtmf_settings;

// -------------------0x0032
u16 custom_tone;
u8 no_used12;
u8 no_used13;
u8 no_used14;
u8 no_used15;
// -------------------0x0038
u8 ch_list;
u16 no_used16;
u16 no_used17;
u16 no_used18;
u8  no_used19;
// -------------------0x0040
ul32 fm_freq;
ul32 sat_freq;
ul32 no_used21;
ul32 no_used22;

// -------------------0x0050
ul16 screen_cha;
ul16 mr_cha;
ul16 freq_cha;
ul16 nooa_cha;
ul16 screen_chb;
ul16 mr_chb;
ul16 freq_chb;
ul16 nooa_chb;


// -------------------0x0150
#seekto 0x150;
char logo_line1[16];
char logo_line2[16];
char qrz_label[8];

// -------------------0x0178
struct 
{
    char dtmf_local_code[8];
    char dtmf_up_code[8];
    char dtmf_down_code[8];
} dtmf_settings_numbers;

// -------------------0x0190
u8 key1_shortpress_action;
u8 key1_longpress_action;
u8 key2_shortpress_action;
u8 key2_longpress_action;

// -------------------0x0198
#seekto 0x0198;
ul32 custom_upconv;

// -------------------0x0200
#seekto 0x200;
struct 
{
    char name[8];
    char number[8];
} dtmfcontact[16];

// -------------------0x0300
#seekto 0x300;
struct 
{
    char name[8];
} list_name[16];

//------------------------------- preset
// -------------------0x0380
struct 
{
  // ---------------rec 1 
  char name[8];

  // ---------------rec 2  
  ul32 freq_low;
  ul32 freq_up;

  // ---------------rec 3
  u8 rxcode;
  u8 txcode;

  u8 tx_codetype:4,
     rx_codetype:4;

  u8 free:1,
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
  
} preset[12];
"""
if IJV_VAR == 0 :   # address per 200 Ch
    MEM_2 = """
    #seekto 0x0500;
    """
else :              # addres 999 Ch
    MEM_2 = """
    #seekto 0x2000;
    """

MEM_3 ="""
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
"""
if IJV_VAR == 0 :       # 200 Ch
    MEM_4 = """  
    } channel[200];
"""
else :                  # 999 Ch
    MEM_4 = """         
    } channel[999];
"""
MEM_5 = """
      //---------------------- Calibration
struct {
    struct {
        #seekto 0x1E00;
        u8 openRssiThr[10];
        #seekto 0x1E10;
        u8 closeRssiThr[10];
        #seekto 0x1E20;
        u8 openNoiseThr[10];
        #seekto 0x1E30;
        u8 closeNoiseThr[10];
        #seekto 0x1E40;
        u8 openGlitchThr[10];
        #seekto 0x1E50;
        u8 closeGlitchThr[10];
    } sqlBand4_7;

    struct {
        #seekto 0x1E60;
        u8 openRssiThr[10];
        #seekto 0x1E70;
        u8 closeRssiThr[10];
        #seekto 0x1E80;
        u8 openNoiseThr[10];
        #seekto 0x1E90;
        u8 closeNoiseThr[10];
        #seekto 0x1EA0;
        u8 openGlitchThr[10];
        #seekto 0x1EB0;
        u8 closeGlitchThr[10];
    } sqlBand1_3;

    #seekto 0x1EC0;
    struct {
        ul16 level1;
        ul16 level2;
        ul16 level4;
        ul16 level6;
    } rssiLevelsBands3_7;

    struct {
        ul16 level1;
        ul16 level2;
        ul16 level4;
        ul16 level6;
    } rssiLevelsBands1_2;

    struct {
        struct {
            u8 lower;
            u8 center;
            u8 upper;
        } low;
        struct {
            u8 lower;
            u8 center;
            u8 upper;
        } mid;
        struct {
            u8 lower;
            u8 center;
            u8 upper;
        } hi;
        #seek 7;
    } txp[7];
    
    
    #seekto 0x1F50;
    ul16 vox1Thr[10];

    #seekto 0x1F68;
    ul16 vox0Thr[10];

    #seekto 0x1F80;
    u8 micLevel[5];

    #seekto 0x1F88;
    il16 xtalFreq;

    #seekto 0x1F8E;
    u8 volumeGain;
    u8 dacGain;
} cal;    
    
    
    #seekto 0x1F48;
    u8 batt_cal0;
    u8 batt_cal1;
    u8 batt_cal2;
    u8 batt_cal3;
    u8 batt_cal4;
    u8 batt_cal5;
    u8 batt_cal6;
    
    #seekto 0x1F90;
    u16 user_code0;
    u16 user_code1;
    u16 user_code2;
    u16 user_code3;
    u16 user_code4;
    u16 user_code5;
    u16 user_code6;
    u16 user_code7;
    u16 user_code8;
    u16 user_code9;
    u16 user_codeA;
    u16 user_codeB;
    u16 user_codeC;
    u16 user_codeD;
    u16 user_codeE;
    u16 user_codeF;

    #seekto 0x1FB0;
    u16 user_code_ms;    

    """

MEM_FORMAT = MEM_1 + MEM_2 +MEM_3 + MEM_4 + MEM_5
# //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\ @variant v3 _ 2 0 0   M E M O R I E //\\//\\//\\//\\//\\//\\//\\//\\//\\
if IJV_VAR == 0 : 
    CHAN_MAX = 200  #  200 Memorie
    MEM_SIZE = 0x2000  # Grandezza massima della memoria 
    PROG_SIZE_V = 0x0050 # fine VFO setting
    PROG_SIZE_U = 0x0140 # inizio User setting
    PROG_SIZE = 0x2000  # Grandezza massima Eprom scrittura Setting //\\//\\ Portare da 0x0500 a 0x2000 per scrivere anche i calibration
    PROG_SIZEM = 0x1e00  # Grandezza massima  Eprom scrittura Memoria
    START_MEM = 0x0500 # Indirizzo di partenza scrittura memorie  
# //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\ Impostazione 200 canali //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\
else :  
# //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\  @variant vX3 _ 9 9 9  M E M O R I E //\\//\\//\\//\\//\\//\\//\\//\\//\\
    CHAN_MAX = 999  # 999 Memorie
    MEM_SIZE = 0x9ce0  # Grandezza massima della memoria 
    PROG_SIZE_V = 0x0050 # fine VFO setting
    PROG_SIZE_U = 0x0140 # inizio User setting
    PROG_SIZE = 0x2000  # Grandezza massima Eprom scrittura Setting //\\//\\ Portare da 0x0500 a 0x2000 per scrivere anche i calibration
    PROG_SIZEM = 0x9ce0  # Grandezza massima Eprom scrittura Memoria 
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

MODULATION_LIST = ["FM","AM","USB","CW","WFM","BYP"]

# dtmf_flags
PTTID_LIST = ["OFF", "CALL ID", "SEL CALL", "CODE BEGIN", "CODE END", "CODE BEG+END",  
              "ROGER Single", "ROGER 2Tones", "MDC 1200", "Apollo Quindar" ]

# power
UVK5_POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=1.00),
                     chirp_common.PowerLevel("Med",  watts=2.50),
                     chirp_common.PowerLevel("High", watts=5.00)]

# scrambler
SCRAMBLER_LIST = ["OFF",
                  "1000Hz","1050Hz","1100Hz","1150Hz","1200Hz","1250Hz","1300Hz","1350Hz","1400Hz","1450Hz",
                  "1500Hz","1550Hz","1600Hz","1650Hz","1700Hz","1750Hz","1800Hz","1850Hz","1900Hz","1950Hz",
                  "2000Hz","2050Hz","2100Hz","2150Hz","2200Hz","2250Hz","2300Hz","2350Hz","2400Hz","2450Hz",
                  "2500Hz","2550Hz","2600Hz","2650Hz","2700Hz","2750Hz","2800Hz","2850Hz","2900Hz","2950Hz",
                  "3000Hz","3050Hz","3100Hz","3150Hz","3200Hz","3250Hz","3300Hz","3350Hz","3400Hz","3450Hz",
                  "3500Hz","3550Hz","3600Hz","3650Hz","3700Hz","3750Hz","3800Hz","3850Hz","3900Hz","3950Hz",
                  "4000Hz","4050Hz","4100Hz"]


#Digital Code
DIGITAL_CODE_LIST = ["OFF","DTMF","ZVEI1","ZVEI2","CCIR-1","CCIR-1F","USER"]

# squelch list
SQUELCH_LIST = ["Squelch 0","Squelch 1","Squelch 2","Squelch 3","Squelch 4","Squelch 5","Squelch 6","Squelch 7","Squelch 8","Squelch 9","NO RX"]

# channel display mode
CHANNELDISP_LIST = ["Frequency", "Channel No", "Channel Name", "Name_S Freq_L", "Name_L Freq_S"]

# VFO/MR
MR_LIST = ["VFO 1","VFO 2","VFO 3","VFO 4","VFO 5","VFO 6","VFO 7"]
MRMODE_LIST = ["MEMORY", "VFO"]
DUALMODE_LIST =["Dual", "Single"]

# Beacon
BEACON_LIST = ["OFF","5 sec","10 sec","30 sec","1 min","3 min","6 min","10 min","20 min"]

# battery save
#BATSAVE_LIST = ["OFF", "50%", "67%", "75%", "80%"]

# compander
COMPANDER_LIST = ["OFF", "TX", "RX", "RX/TX"]

# mic gain
MICGAIN_LIST = ["+1.1dB","+4.0dB","+8.0dB","+12.0dB","+15.1dB"]

# Talk Time
TALKTIME_LIST = ["OFF","30s","1min","3min","5min"]

# Backlight auto mode
BACKLIGHT_LIST = ["Off", "5s", "10s", "20s", "1min", "3min", "RX/TX", "ON"]

# Memory Speed
# MEMSPEED_LIST = ["6ms", "7ms", "8ms", "9ms", "10ms", "11ms", "12ms", "13ms", "14ms", "15ms", "16ms", "17ms", "18ms", "19ms", "20ms", "21ms", "22ms", "23ms", "24ms", "25ms"]

# Crossband receiving/transmitting
VFOMODE_LIST = ["SINGLE","DOUBLE","DW_LOCK","DW_LINK","SPLIT"]
# DUALWATCH_LIST = ["OFF", "On"]
BANDS_TX_LIST  = ["A","B"]

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

AGC_LIST = ["-84", "-83", "-82", "-81", "-80", "-78", "-76", "-74", "-72", "-70", "-68", "-66", "-62", "-60", "-58",
            "-56", "-52", "-50", "-48", "-46", "-42", "-40", "-38", "-35", "-31", "-29", "-28", "-27", "-26", "-24",
            "-21", "-18", "-16", "-13", "-11", "-8", "-6", "-5", "-3" , "-2" , "-1" , "0"  ]

AGC_CORR = [18,26,26,26,18,18,18]

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

FLOCK_LIST = ["OFF", "FCC", "CE", "GB", "430", "438"]

SCANRESUME_LIST = ["TIME: Resume after 5 seconds",
                   "SLOW: Resume slower after signal disappears",
                   "FAST: Resume faster after signal disappears",
                   "SEARCH: Stop scanning after receiving a signal",
                   "LOG"]

WELCOME_LIST = ["None", "FW Mod", "Message"]

RTE_LIST = ["OFF", 
            "1*100ms", "2*100ms", "3*100ms", "4*100ms", "5*100ms",
            "6*100ms", "7*100ms", "8*100ms", "9*100ms", "10*100ms",
            "11*100ms", "12*100ms", "13*100ms", "14*100ms", "15*100ms",
            "16*100ms", "17*100ms", "18*100ms", "19*100ms", "20*100ms"]



# fm radio supported frequencies
FMMIN = 76.0
FMMAX = 108.0



# Custom Tone f max
CTMAX = 255.0

UCODMAX = 3000.0

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
BANDSTX_CAL = [" (13~108 MHz)"," (108~137 MHz)"," (137~174 MHz)"," (174~350 MHz)"," (350~400 MHz)"," (400~470 MHz)"," (470~1300 MHz)"]

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

VFO_CHANNEL_NAMES = ["F1(50M-76M)A",   "F1(50M-76M)B",
                     "F2(108M-136M)A", "F2(108M-136M)B",
                     "F3(136M-174M)A", "F3(136M-174M)B",
                     "F4(174M-350M)A", "F4(174M-350M)B",
                     "F5(350M-400M)A", "F5(350M-400M)B",
                     "F6(400M-470M)A", "F6(400M-470M)B",
                     "F7(470M-600M)A", "F7(470M-600M)B"]

DTMF_CHARS = "0123456789ABCDEF*# "
DTMF_CHARS_ID = "0123456789ABCDabcdef#* "

DTMF_CHARS_UPDOWN = "0123456789ABCDEFabcdef#* "
DTMF_CODE_CHARS = "ABCDEF*# "
DTMF_DECODE_RESPONSE_LIST = ["None", "Ring", "Reply", "Both"]
DLIVE_LIST = "off", "RAW", "POP"
KEYACTIONS_LIST = ["None",
                   "Flashlight",
                   "TX Power",
                   "Monitor",
                   "Scan on/off",
                   "FM radio on/off",
                   "VFO Change",
                   "VFO Swap", 
                   "SQL +",
                   "SQL -",
                   "REGA Test",
                   "REGA Alarm", 
                   "Preset",
                   "AGC MAN",
                   "CH LIST",
                   "SCRAMBLER",
                   "PHONE BOOK",
                   "CW Call CQ"]

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

UPCONV_LIST = ["OFF","50 MHz", "125 MHz","CUSTOM"]

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
    status.msg = "Uploading VFO Setting to radio"
    radio.status_fn(status)

    f = _sayhello(serport)
    if f:
        radio.FIRMWARE_VERSION = f
    else:
        return False
#---------------Scrittura setting 1  
    addr = 0
    while addr < PROG_SIZE_V:
        o = radio.get_mmap()[addr:addr+MEM_BLOCK]
        _writemem(serport, o, addr)
        status.cur = addr
        radio.status_fn(status)
        if o:
            addr += MEM_BLOCK
        else:
            raise errors.RadioError("Upload VFO incomplete")
    status.msg = "Uploading User Setting to radio"
#---------------Scrittura setting 2 
    addr = PROG_SIZE_U
    while addr < PROG_SIZE:
        o = radio.get_mmap()[addr:addr+MEM_BLOCK]
        _writemem(serport, o, addr)
        status.cur = addr
        radio.status_fn(status)
        if o:
            addr += MEM_BLOCK
        else:
            raise errors.RadioError("Upload User Setting incomplete")
    status.msg = "Uploading Memory to radio"    
#----------------Scrittura Memorie
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
    def get_prompts(x=None):
        rp = chirp_common.RadioPrompts()
        rp.experimental = _(
            'This is an experimental driver for the Quansheng UV-K5. '
            'It may harm your radio, or worse. Use at your own risk.\n\n'
            'Before attempting to do any changes please download '
            'the memory image from the radio with chirp '
            'and keep it. This can be later used to recover the '
            'original settings. \n\n'
            'some details are not yet implemented')
        rp.pre_download = _(
            "1. Turn radio on.\n"
            "2. Connect cable to mic/spkr connector.\n"
            "3. Make sure connector is firmly connected.\n"
            "4. Click OK to download image from device.\n\n"
            "It will may not work if you turn on the radio "
            "with the cable already attached\n")
        rp.pre_upload = _(
            "1. Turn radio on.\n"
            "2. Connect cable to mic/spkr connector.\n"
            "3. Make sure connector is firmly connected.\n"
            "4. Click OK to upload the image to device.\n\n"
            "It will may not work if you turn on the radio "
            "with the cable already attached")
        return rp

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

        basic = RadioSettingGroup("basic",  "Basic Settings")
        vfoch = RadioSettingGroup("vfoch",  "VFO / Channel Mode")
        agc   = RadioSettingGroup("agc",    "RF Gain Settings")
        keya  = RadioSettingGroup("keya",   "Programmable keys")
        dtmf  = RadioSettingGroup("dtmf",   "DTMF/5Tone Settings")
        # utone = RadioSettingGroup("utone", "User 5Tone ")
        dtmfc = RadioSettingGroup("dtmfc",  "PHONE BOOK")
        lstn  = RadioSettingGroup("lstn",   "Memory Group")
        preset = RadioSettingGroup("preset", "Preset List")
        expert = RadioSettingGroup("expert",  "Expert Settings")
        calibration = RadioSettingGroup("calibration", _("***Calibration,Don't touch if you don't know what to do*** "))
        roinfo = RadioSettingGroup("roinfo", _("Driver information"))

        # top = RadioSettings( basic, vfoch, agc, keya, dtmf, utone, dtmfc, lstn, preset, expert, calibration, roinfo )
        top = RadioSettings( basic, vfoch, agc, keya, dtmf, dtmfc, lstn, preset, expert, calibration, roinfo )
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



        #********************************************************************************** SEZIONE TASTI PROGRAMMABILI
        append_label(keya,"_" * 30 + " Programmable Key  " + "_" * 274, "_" * 300)    
        # Programmable keys
        tmpval = int(_mem.key1_shortpress_action)
        if tmpval >= len(KEYACTIONS_LIST):
            tmpval = 0
        rs = RadioSetting("key1_shortpress_action", "Side key 1 short press",
                          RadioSettingValueList(KEYACTIONS_LIST, KEYACTIONS_LIST[tmpval]))
        keya.append(rs)

        tmpval = int(_mem.key1_longpress_action)
        if tmpval >= len(KEYACTIONS_LIST):
            tmpval = 0
        rs = RadioSetting("key1_longpress_action", "Side key 1 long press",
                          RadioSettingValueList(KEYACTIONS_LIST, KEYACTIONS_LIST[tmpval]))
        keya.append(rs)

        tmpval = int(_mem.key2_shortpress_action)
        if tmpval >= len(KEYACTIONS_LIST):
            tmpval = 0
        rs = RadioSetting("key2_shortpress_action", "Side key 2 short press",
                          RadioSettingValueList(KEYACTIONS_LIST, KEYACTIONS_LIST[tmpval]))
        keya.append(rs)

        tmpval = int(_mem.key2_longpress_action)
        if tmpval >= len(KEYACTIONS_LIST):
            tmpval = 0
        rs = RadioSetting("key2_longpress_action", "Side key 2 long press",
                          RadioSettingValueList(KEYACTIONS_LIST, KEYACTIONS_LIST[tmpval]))
        keya.append(rs)

        append_label(keya," " * 40 + "|     |                          " )
        append_label(keya," " * 40 + "|     |                          " )
        append_label(keya," " * 40 + "|     |                          " )
        append_label(keya," " * 40 + "|     |                          " )
        append_label(keya," " * 40 + "|     |___________ |        |" )
        append_label(keya," " * 40 + "|      ____________      /" )
        append_label(keya," " * 39 +"||     |                     |    |" )
        append_label(keya," " * 30 +" PTT  |" "|     |                     |    |" )
        append_label(keya," " * 39 +" |     |____________|    |" )
        append_label(keya," " * 21 +"Side key 1 |" "|          /  /  /  /          |" )
        append_label(keya," " * 21 +"Side key 2 |" "|          /  /  /  /          |" )
        append_label(keya," " * 41 + "|                                |" )
        append_label(keya," " * 41 + "|                                |" )
        append_label(keya," " * 41 + "|                                |" )
        append_label(keya," " * 41 + "|_________________  |" )



        #********************************************************************************** SEZIONE DTMF
        append_label(dtmf, "_" * 30 + " DTMF Setting  " + "_" * 274, "_" * 300)

        # DTMF settings

        
        tmpval = _mem.dtmf_settings.auto_reset_time
        if tmpval > 61 or tmpval < 4:
            tmpval = 4
        rs = RadioSetting("dtmf_auto_reset_time","DTMF Auto reset time (s)",RadioSettingValueInteger(4, 61, tmpval))
        dtmf.append(rs)

        tmpval = int(_mem.dtmf_settings.preload_time)
        if tmpval > 100 or tmpval < 3:     # se leggero' un valore maggiore di 100(x10) o meno di 3(x10) 
            tmpval = 30                    # il valore verrà impostato a 30 
        tmpval *= 10                       # moltiplico per 10
        rs = RadioSetting("dtmf_preload_time","DTMF Pre-load time (ms)",RadioSettingValueInteger(30, 1000, tmpval, 10)) #  30 minimo 1000 massimo ,con step di 10
        dtmf.append(rs)

        
        tmpval = int(_mem.dtmf_settings.hash_persist_time)
        if tmpval > 100 or tmpval < 3:
            tmpval = 30
        tmpval *= 10
        rs = RadioSetting("dtmf_hash_persist_time","DTMF #/* persist time (ms)",RadioSettingValueInteger(30, 1000, tmpval, 10))
        dtmf.append(rs)

        tmpval = int(_mem.dtmf_settings.code_persist_time)
        if tmpval > 100 or tmpval < 3:
            tmpval = 30
        tmpval *= 10
        rs = RadioSetting("dtmf_code_persist_time","DTMF Code persist time (ms)",RadioSettingValueInteger(30, 1000, tmpval, 10))
        dtmf.append(rs)

        tmpval = int(_mem.dtmf_settings.code_interval_time)
        if tmpval > 100 or tmpval < 3:
            tmpval = 30
        tmpval *= 10
        rs = RadioSetting("dtmf_code_interval_time","DTMF Code interval time (ms)",RadioSettingValueInteger(30, 1000, tmpval, 10))
        dtmf.append(rs)

        append_label(dtmf, "_" * 10 + " DTMF/5Tone Setting  (1-8 chars 0-9 ABCDEF)" + "_" * 274, "_" * 300)
        tmpval = str(_mem.dtmf_settings_numbers.dtmf_local_code).upper().strip("\x00\xff\x20")

        for i in tmpval:
            if i in DTMF_CHARS_ID:
                continue
            else:
                tmpval = "103"
                break
        val = RadioSettingValueString(1, 8, tmpval)
        val.set_charset(DTMF_CHARS_ID)
        rs = RadioSetting("dtmf_dtmf_local_code","DTMF/5Tone OWN ID (used also as ID REGA) ", val)
        dtmf.append(rs)

        tmpval = str(_mem.dtmf_settings_numbers.dtmf_up_code).upper().strip("\x00\xff\x20")
        
        for i in tmpval:
            if i in DTMF_CHARS_UPDOWN or i == "":
                continue
            else:
                tmpval = "123"
                break
        val = RadioSettingValueString(1, 8, tmpval)
        val.set_charset(DTMF_CHARS_UPDOWN)
        rs = RadioSetting("dtmf_dtmf_up_code","DTMF/5tone Up code ***(valid only in VFO Mode)", val)
        dtmf.append(rs)

        tmpval = str(_mem.dtmf_settings_numbers.dtmf_down_code).upper().strip("\x00\xff\x20")

        for i in tmpval:
            if i in DTMF_CHARS_UPDOWN:
                continue
            else:
                tmpval = "456"
                break
        val = RadioSettingValueString(1, 8, tmpval)
        val.set_charset(DTMF_CHARS_UPDOWN)
        rs = RadioSetting("dtmf_dtmf_down_code","DTMF/5Tone Down code ***(valid only in VFO Mode)", val)
        dtmf.append(rs)

        tmppr = bool(_mem.dtmf_settings.side_tone > 0)
        rs = RadioSetting("dtmf_side_tone","DTMF/5Tone Sidetone",RadioSettingValueBoolean(tmppr))
        dtmf.append(rs)

        # DTMF/5tone LIVE
        
        tmpdlive = _mem.dtmf_live
        if tmpdlive >= len(DLIVE_LIST):
            tmpdlive = 0
        rs = RadioSetting("dtmf_live","DTMF/5Tone Live ",RadioSettingValueList(DLIVE_LIST,DLIVE_LIST[tmpdlive]))
        dtmf.append(rs)


        tmpval = str(_mem.dtmf_settings.separate_code)
        if tmpval not in DTMF_CODE_CHARS:
            tmpval = '*'
        val = RadioSettingValueString(1, 1, tmpval)
        val.set_charset(DTMF_CODE_CHARS)
        rs = RadioSetting("dtmf_separate_code", "DTMF/5Tone Separation Code", val)
        dtmf.append(rs)

        tmpval = str(_mem.dtmf_settings.group_call_code)
        if tmpval not in DTMF_CODE_CHARS:
            tmpval = '#'
        val = RadioSettingValueString(1, 1, tmpval)
        val.set_charset(DTMF_CODE_CHARS)
        rs = RadioSetting("group_call_code", "DTMF/5Tone Group Call Code", val)
        dtmf.append(rs)

        tmpval = _mem.dtmf_settings.decode_response
        if tmpval >= len(DTMF_DECODE_RESPONSE_LIST):
            tmpval = 0
        rs = RadioSetting("dtmf_decode_response", "DTMF/5Tone Decode Response",RadioSettingValueList(DTMF_DECODE_RESPONSE_LIST,DTMF_DECODE_RESPONSE_LIST[tmpval]))
        dtmf.append(rs)

        tmpval = int(_mem.dtmf_settings.first_code_persist_time)
        if tmpval > 300 : #or tmpval < 3:
            tmpval = 0
        tmpval *= 10
        rs = RadioSetting("dtmf_first_code_persist_time","DTMF/5Tone First code persist time; length added to the first tone (ms)",RadioSettingValueInteger(0, 300, tmpval, 10))
        dtmf.append(rs)


        # append_label(dtmfc,
        #              "_" * 30 + " DTMF Contact List " + "_" * 274, "_" * 300)

        val = RadioSettingValueString(0, 80,
                                      "All DTMF/5Tone Contacts are 8 codes "
                                      "(valid: 0-9 * # ABCD), "
                                      "or an empty string")
        val.set_mutable(False)
        rs = RadioSetting("dtmf_descr1", "PHONE GROUP", val)
        dtmfc.append(rs)

        #********************************************************************************* USER TONE 5Tone
        
        # append_label(utone, "_" * 30 + " 5Tone User Code (500 ~ 3000 Hz)  " + "_" * 274, "_" * 300)
        
        # tmpval = int(_mem.user_code0)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
        # #tmpval *=10  
        # rs = RadioSetting("user_code0", "User Code 0 ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs)   

        # tmpval = int(_mem.user_code1)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_code1", "User Code 1 ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs) 

        # tmpval = int(_mem.user_code2)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_code2", "User Code 2 ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs) 

        # tmpval = int(_mem.user_code3)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_code3", "User Code 3 ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs) 

        # tmpval = int(_mem.user_code4)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_code4", "User Code 4 ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs) 

        # tmpval = int(_mem.user_code5)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_code5", "User Code 5 ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs) 

        # tmpval = int(_mem.user_code6)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_code6", "User Code 6 ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs) 

        # tmpval = int(_mem.user_code7)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_code7", "User Code 7 ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs) 

        # tmpval = int(_mem.user_code8)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_code8", "User Code 8 ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs)
        # tmpval = int(_mem.user_code9)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_code9", "User Code 9 ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs) 

        # tmpval = int(_mem.user_codeA)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_codeA", "User Code A ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs)

        # tmpval = int(_mem.user_codeB)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_codeB", "User Code B ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs)

        # tmpval = int(_mem.user_codeC)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_codeC", "User Code C ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs)

        # tmpval = int(_mem.user_codeD)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_codeD", "User Code D ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs) 

        # tmpval = int(_mem.user_codeE)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_codeE", "User Code E ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs)

        # tmpval = int(_mem.user_codeF)
        # if tmpval  > 3000 or tmpval < 400:
        #    tmpval = 1000
             
        # rs = RadioSetting("user_codeF", "User Code F ",
        #                           RadioSettingValueInteger(400, 3000, tmpval,5))
        # utone.append(rs)      

        # append_label(utone, "_" * 30 + " 5Tone User Code Length (30 ~ 300 ms)  " + "_" * 274, "_" * 300)

        # tmpval = int(_mem.user_code_ms)
        # if tmpval > 300 or tmpval < 30 : 
        #     tmpval = 70
        # #tmpval *= 10
        # rs = RadioSetting("user_code_ms","5Tone User Code length (ms)",RadioSettingValueInteger(30, 300, tmpval, 1))
        # utone.append(rs)
       
        #********************************************************************************** SEZIONE CONTATTI DTMF

        for i in range(1, 17):
            append_label(dtmfc, "_" * 30 + " PHONE GROUP #" + str(i)) 
            varname = "DTMF_"+str(i)
            varnumname = "DTMFNUM_"+str(i)
            vardescr = "Contact "+str(i)+" name"
            varinumdescr = "Contact "+str(i)+" number"

            cntn = str(_mem.dtmfcontact[i-1].name).strip("\x20\x00\xff")
            cntnum = str(_mem.dtmfcontact[i-1].number).strip("\x20\x00\xff")

            val = RadioSettingValueString(0, 8, cntn)
            rs = RadioSetting(varname, vardescr, val)
            dtmfc.append(rs)

            val = RadioSettingValueString(0, 8, cntnum)
            val.set_charset(DTMF_CHARS)
            rs = RadioSetting(varnumname, varinumdescr, val)
            dtmfc.append(rs)

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


        #********************************************************************************** SEZIONE AGC
        # AGC
        append_label(agc, "_" * 30 + " RF Gain Band Setting " + "_" * 274, "_" * 300)

        val = RadioSettingValueString(0, 80,"RF Gain Value (dBM) (** READ ONLY **)")
        val.set_mutable(False)
        rs = RadioSetting("agc_descr", "RF Gain VFO #", val)
        agc.append(rs)

        for i in range(1, 8):
            nagc = "agc_"+str(i)
            dagc = "RF Gain VFO "+str(i)+" "
            vagc = _mem.agc[i-1].val
            vagcd = AGC_CORR[i-1] + int(AGC_LIST[vagc])


            temp = RadioSettingValueString(len(str(vagcd)), len(str(vagcd)), str(vagcd))
            temp.set_mutable(False)

            rs = RadioSetting(nagc,dagc,temp)
            agc.append(rs)       


        #********************************************************************************** SEZIONE PRESET
        # PRESET

        for i in range(1, 13):
            append_label(preset, "_" * 30 + " PRESET " + str(i) + "_" * 274, "_" * 300)

            #----------------------------------------------- name
            varlist = "Preset_Name_"+str(i)
            vardescrl = "Preset Name "+str(i)

            cntnl = str(_mem.preset[i-1].name).strip("\x20\x00\xff")
            val = RadioSettingValueString(0, 8, cntnl)
            rs = RadioSetting(varlist, vardescrl, val)
            preset.append(rs)
            #----------------------------------------------- freq low
            freqlow = "Low_Range_"+str(i)
            lowdesc = "Low Range "
            # flow = _mem.preset[i-1].freq_low

            # rs = RadioSetting(freqlow,lowdesc,RadioSettingValueInteger(0, 130000000, flow, 1))

            flow = _mem.preset[i-1].freq_low/100000.0
            if flow  > 1300.00000:
                    rs = RadioSetting(freqlow, lowdesc,
                           RadioSettingValueString(0, 10, "1300.00000"))
            else:
                    rs = RadioSetting(freqlow, lowdesc,
                           RadioSettingValueString(0, 10, str(flow)))

            preset.append(rs)
            #----------------------------------------------- freq up
            frequp = "Up_Range_"+str(i)
            updesc = "Up Range "
            # fup = _mem.preset[i-1].freq_up  

            # rs = RadioSetting(frequp,updesc,RadioSettingValueInteger(0, 130000000, fup, 1))
            fup = _mem.preset[i-1].freq_up/100000.0
            if fup  > 1300.00000:
                    rs = RadioSetting(frequp, updesc,
                           RadioSettingValueString(0, 10, "1300.00000"))
            else:
                    rs = RadioSetting(frequp, updesc,
                           RadioSettingValueString(0, 10, str(fup)))

            preset.append(rs)

            #----------------------------------------------- step
            step = "Step_"+str(i)
            stepdesc = "Step "
            vstep = _mem.preset[i-1].step
            if vstep >= len(STEP_LIST):
                  vstep = 10

            rs = RadioSetting(step,stepdesc,RadioSettingValueList(STEP_LIST,STEP_LIST[vstep]))
            preset.append(rs)

            #-----------------------------------------------Tx Power
            txpower = "TX Power_"+str(i)
            txpowerdesc = "TX Power "
            vtxpower = _mem.preset[i-1].txpower
            if vtxpower >= len(TXPOWER_LIST):
                  vtxpower = 0

            rs = RadioSetting(txpower,txpowerdesc,RadioSettingValueList(TXPOWER_LIST,TXPOWER_LIST[vtxpower]))
            preset.append(rs)

            #----------------------------------------------- bw
            sbw = "Bw_"+str(i)
            dbw = "BW "
            vbw = _mem.preset[i-1].bw
            if vbw >= len(BANDWIDTH_LIST):
                vbw = 0

            rs = RadioSetting(sbw,dbw,RadioSettingValueList(BANDWIDTH_LIST,BANDWIDTH_LIST[vbw]))
            preset.append(rs)
            
            #----------------------------------------------- agc
            sagc = "AGC_"+str(i)
            dagc = "AGC "
            vagc = _mem.preset[i-1].agcmode
            if vagc >= len(AGC_MODE):
                vagc = 0

            rs = RadioSetting(sagc,dagc,RadioSettingValueList(AGC_MODE,AGC_MODE[vagc]))
            preset.append(rs)

            #----------------------------------------------- Modulation
            smod = "Mode_"+str(i)
            dmod = "Mode "
            vmod = _mem.preset[i-1].modulation
            if vmod >= len(MODULATION_LIST):
                vmod = 0
  
            rs = RadioSetting(smod,dmod,RadioSettingValueList(MODULATION_LIST,MODULATION_LIST[vmod]))
            preset.append(rs)

            #----------------------------------------------- Squelch
            ssq = "Sql_"+str(i)
            dsq = "Squelch "
            if _mem.preset[i-1].squelch < len(SQUELCH_LIST):
                vsql = _mem.preset[i-1].squelch
            else:
                vsql = 1  

            rs = RadioSetting(ssq,dsq,RadioSettingValueList(SQUELCH_LIST,SQUELCH_LIST[vsql]))
            preset.append(rs)

        #********************************************************************************** SEZIONE SETTAGGI DI BASE
        append_label(basic, "_" * 30 + " Display settings " + "_" * 274, "_" * 300)




        # Backlight auto mode
        tmpback = _mem.backlight_auto_mode
        if tmpback >= len(BACKLIGHT_LIST):
            tmpback = 0
        rs = RadioSetting("backlight_auto_mode","BackLightTime",RadioSettingValueList(BACKLIGHT_LIST,BACKLIGHT_LIST[tmpback]))
        basic.append(rs)
        
        # BLMode
        rs = RadioSetting("bl_mode","BLmode (TX/RX)", RadioSettingValueBoolean(bool(_mem.bl_mode > 0)))
        basic.append(rs)

        # Inversione display
        rs = RadioSetting("back_type","Display Inverted",RadioSettingValueBoolean(bool(_mem.back_type > 0)))
        basic.append(rs)

        # RSSI / S Meter BIT 2
        # rs = RadioSetting("signal_meter","SMeter (instead of RSSI for dual VFO)", RadioSettingValueBoolean(bool(_mem.signal_meter > 0)))
        # basic.append(rs)

        # MicBar
        rs = RadioSetting("micbar","MicBar", RadioSettingValueBoolean(bool(_mem.micbar > 0)))
        basic.append(rs)

        # Power on display mode
        tmpdispmode = _mem.power_on_dispmode
        if tmpdispmode >= len(WELCOME_LIST):
            tmpdispmode = 0
        rs = RadioSetting("welcome_mode","Power on display MSG",RadioSettingValueList(WELCOME_LIST,WELCOME_LIST[tmpdispmode]))
        basic.append(rs)

        append_label(basic, "_" * 30 + " Audio settings " + "_" * 274, "_" * 300)
        # Beep control
        rs = RadioSetting("beep_control","Beep control",RadioSettingValueBoolean(bool(_mem.beep_control > 0)))
        basic.append(rs)

         # Mic gain
        tmpmicgain = _mem.mic_gain
        if tmpmicgain >= len(MICGAIN_LIST):
            tmpmicgain = MICGAIN_LIST.index("+12.0dB")
        rs = RadioSetting("mic_gain","Mic Gain",RadioSettingValueList(MICGAIN_LIST,MICGAIN_LIST[tmpmicgain]))
        basic.append(rs)

        # VOX switch
        #rs = RadioSetting("vox_switch","VOX enabled", RadioSettingValueBoolean(bool(_mem.vox_switch > 0)))
        #basic.append(rs)

        # VOX Level
        # tmpvox = _mem.vox_level+1
        # if tmpvox > 10:
            # tmpvox = 10
        # rs = RadioSetting("vox_level", "VOX Level",RadioSettingValueInteger(1, 10, tmpvox))
        # basic.append(rs)


        append_label(basic, "_" * 30 + " Key Lock settings " + "_" * 274, "_" * 300)

        # Keypad locked
        rs = RadioSetting("key_lock","Keypad Lock",RadioSettingValueBoolean(bool(_mem.key_lock > 0)))
        basic.append(rs)

        # Auto keypad lock
        rs = RadioSetting("auto_keypad_lock","Auto keypad lock",RadioSettingValueBoolean(bool(_mem.auto_keypad_lock > 0)))
        basic.append(rs)

        append_label(basic, "_" * 30 + " RTX settings " + "_" * 274, "_" * 300)

        # Vfo mode
        tmpvfo = _mem.vfomode
        if tmpvfo >= len(VFOMODE_LIST):
            tmpvfo = 0
        rs = RadioSetting("vfomode","VFO mode ",RadioSettingValueList(VFOMODE_LIST,VFOMODE_LIST[tmpvfo]))
        basic.append(rs)

        # Band TX
        tmpbandstx = _mem.bands_tx
        if tmpbandstx >= len(BANDS_TX_LIST):
            tmpbandstx = 0
        rs = RadioSetting("bands_tx", "Bands TX", RadioSettingValueList(BANDS_TX_LIST, BANDS_TX_LIST[tmpbandstx]))
        basic.append(rs)

        append_label(basic, "_" * 30 + " Beacon/CQ Call settings " + "_" * 274, "_" * 300)

        # Beacon
        tmpbeacon = _mem.beacon
        if tmpbeacon >= len(BEACON_LIST):
            tmpbeacon = BEACON_LIST.index("OFF")
        rs = RadioSetting("beacon","Beacon/CQ Call",RadioSettingValueList(BEACON_LIST,BEACON_LIST[tmpbeacon]))
        basic.append(rs)

        # QRZ label
        qrz_label = str(_mem.qrz_label).rstrip("\x20\x00\xff") + "\x00"
        qrz_label = _getstring(qrz_label.encode('ascii', errors='ignore'), 0, 8)
        rs = RadioSetting("qrz_label", _("QRA (8 characters)"), RadioSettingValueString(0, 8, qrz_label))
        basic.append(rs)

        # Logo string 1
        logo1 = str(_mem.logo_line1).strip("\x20\x00\xff") + "\x00"
        logo1 = _getstring(logo1.encode('ascii', errors='ignore'), 0, 16)
        rs = RadioSetting("logo1", _("Logo string 1 (16 characters)"), RadioSettingValueString(0, 16, logo1))
        basic.append(rs)

        # Logo string 2
        logo2 = str(_mem.logo_line2).strip("\x20\x00\xff") + "\x00"
        logo2 = _getstring(logo2.encode('ascii', errors='ignore'), 0, 16)
        rs = RadioSetting("logo2", _("Logo string 2 (16 characters)"), RadioSettingValueString(0, 16, logo2))
        basic.append(rs)

        append_label(basic, "_" * 30 + " Other settings " + "_" * 274, "_" * 300)

        # TOT
        tmptot = _mem.max_talk_time
        if tmptot >= len(TALKTIME_LIST):
            tmptot = TALKTIME_LIST.index("3min")
        rs = RadioSetting("max_talk_time","Max talk time (Tx TOT)",RadioSettingValueList(TALKTIME_LIST,TALKTIME_LIST[tmptot]))
        basic.append(rs)

        # Battery save
        #tmpbatsave = _mem.battery_save
        #if tmpbatsave >= len(BATSAVE_LIST):
        #    tmpbatsave = BATSAVE_LIST.index("80%")
        #rs = RadioSetting("battery_save","Battery Save",RadioSettingValueList(BATSAVE_LIST,BATSAVE_LIST[tmpbatsave]))
        #basic.append(rs)


        # Scan resume mode
        tmpscanres = _mem.scan_resume_mode
        if tmpscanres >= len(SCANRESUME_LIST):
            tmpscanres = 0
        rs = RadioSetting("scan_resume_mode","Scan resume mode (Sc REV)",RadioSettingValueList(SCANRESUME_LIST,SCANRESUME_LIST[tmpscanres]))
        basic.append(rs)

        #________________________________________________________________________________      
        append_label(vfoch, "_" * 300 + "_" * 274, "_" * 300)       
        # Channel display mode
        tmpchdispmode = _mem.channel_display_mode
        if tmpchdispmode >= len(CHANNELDISP_LIST):
            tmpchdispmode = 0
        rs = RadioSetting("channel_display_mode","Channel Display mode",RadioSettingValueList( CHANNELDISP_LIST, CHANNELDISP_LIST[tmpchdispmode]))
        vfoch.append(rs)

        # Single VFO 
        # val = _mem.single_vfo
        # rs = RadioSetting("single_vfo","Dual/Single Band", #RadioSettingValueBoolean(bool(_mem.single_vfo > 0)))
        #                   RadioSettingValueList(DUALMODE_LIST, DUALMODE_LIST[val]))
        # vfoch.append(rs)



        # call channel
        tmpc = _mem.call_channel+1
        if tmpc > CHAN_MAX:
            tmpc = 1
        rs = RadioSetting("call_channel", "Call channel",RadioSettingValueInteger(1, CHAN_MAX, tmpc))
        vfoch.append(rs)


        #************************** EXPERT SETTING ******************************************************** 

        append_label(expert, "_" * 30 + " Expert settings " + "_" * 274, "_" * 300)

        # Tail tone elimination
        rs = RadioSetting("tail_note_elimination","TX Squelch Tail Elimination",RadioSettingValueBoolean(bool(_mem.tail_note_elimination > 0)))
        expert.append(rs)

        # Repeater tail tone elimination
        tmprte = _mem.repeater_tail_elimination
        if tmprte >= len(RTE_LIST):
            tmprte = 0
        rs = RadioSetting("repeater_tail_elimination","RX Squelch Tail Elimination",RadioSettingValueList(RTE_LIST, RTE_LIST[tmprte]))
        expert.append(rs)

        # TX Enable
        rs = RadioSetting("tx_enable","TX enable", RadioSettingValueBoolean(bool(_mem.tx_enable > 0)))
        expert.append(rs)

        # VFO open
        rs = RadioSetting("vfo_lock", "VFO hidden", RadioSettingValueBoolean(bool(_mem.vfo_lock > 0)))
        expert.append(rs)

        # Custom tone
        custom_tone = _mem.custom_tone/10.0
        if custom_tone  > CTMAX:
                rs = RadioSetting("custom_tone", "CTCSS Custom Tone (0 ~ 255 Hz)",
                                  RadioSettingValueString(0, 5, "255.0"))
        else:
                rs = RadioSetting("custom_tone", "CTCSS Custom Tone (0 ~ 255 Hz)",
                                  RadioSettingValueString(0, 5, str(custom_tone)))
        expert.append(rs)   
        
        append_label(expert, " " * 300 , " " * 300)
        # afc
        if _mem.afc > 7:
            _mem.afc = 7
        rs = RadioSetting("afc", "AFC (0~7)",RadioSettingValueInteger(0, 7, _mem.afc))
        expert.append(rs)
                
        # tx_dev
        if _mem.tx_dev > 9:
            _mem.tx_dev = 9
        rs = RadioSetting("tx_dev", "Tx Deviation(0=Standard, 9=Max deviation)",RadioSettingValueInteger(0, 9, _mem.tx_dev))
        expert.append(rs)
        #savedirect
        rs = RadioSetting("savedirect","AutoSave ", RadioSettingValueBoolean(bool(_mem.savedirect > 0)))
        expert.append(rs)

        # SATCOM
        append_label(expert, "_" * 30 + " SATCOM " + "_" * 274, "_" * 300)
        # Satcom enable 
        # rs = RadioSetting("satcom","Boost", RadioSettingValueBoolean(bool(_mem.satcom > 0)))
        # expert.append(rs)

        # Sat Frequency  Switch
        sat_freq = _mem.sat_freq/100000.0
        if sat_freq  > 290.00000 or sat_freq < 210.00000 :
                rs = RadioSetting("sat_freq", "Sat Switch Frequency (range 210 ~ 290.00000 MHz)",RadioSettingValueString(0, 9, "280.00000"))
        else:
                rs = RadioSetting("sat_freq", "Sat Switch Frequency (range 210 ~ 290.00000 MHz)",RadioSettingValueString(0, 9, str(sat_freq)))
        expert.append(rs) 
        

        # UPCONVERTER
        append_label(expert, " " * 300 , " " * 300)
        append_label(expert, "_" * 30 + " UP CONVERTER " + "_" * 274, "_" * 300)

        # Upconv 
        tmpupconv = _mem.upconv 
        if tmpupconv >= len(UPCONV_LIST):
            tmpupconv = UPCONV_LIST.index("OFF")
        rs = RadioSetting("upconv","UP Converter", RadioSettingValueList(UPCONV_LIST,UPCONV_LIST[tmpupconv]))
        expert.append(rs)

        #Custom Frequency Upconverter
        custom_upconv = _mem.custom_upconv/100000.0
        if custom_upconv  > 999.99999:
                rs = RadioSetting("custom_upconv", "Custom Upconvrerter Frequency (max 999.99999 MHz)",RadioSettingValueString(0, 9, "999.99999"))
        else:
                rs = RadioSetting("custom_upconv", "Custom Upconvrerter Frequency (max 999.99999 MHz)",RadioSettingValueString(0, 9, str(custom_upconv)))
        expert.append(rs)    


                
        # Calibration 
        # val = RadioSettingValueBoolean(False)

        # radio_setting = RadioSetting("upload_calibration",
        #                              "Upload calibration", val)
        # radio_setting.set_warning(
        #     _('This option may break your radio! '
        #       'Each radio has a unique set of calibration data '
        #       'and uploading the data from the image will cause '
        #       'physical harm to the radio if it is from a '
        #       'different piece of hardware. Do not use this '
        #       'unless you know what you are doing and accept the '
        #       'risk of destroying your radio!'),
        #     safe_value=False)
        # calibration.append(radio_setting)
        #_________BATTERY Calibration_________________________________________________________
        radio_setting_group = RadioSettingGroup("other0_calibration", "BattCal")
        calibration.append(radio_setting_group)

        append_label(radio_setting_group, " " * 300 , " " * 300)
        append_label(radio_setting_group, "_" * 30 + " BATTERY CALIBRATION " + "_" * 274, "_" * 300)
        
        batt_cal0 = _mem.batt_cal0/100.0
        radio_setting = RadioSetting("batt_cal0", "Voltage Calibration (Volt)",
                          RadioSettingValueString(0, 3, str(batt_cal0)))
        radio_setting_group.append(radio_setting)
        append_label(radio_setting_group, " " * 300 , " " * 300)
        append_label(radio_setting_group, "_" * 30 + " Icon bar Trheshold CALIBRATION " + "_" * 274, "_" * 300)

        batt_cal1 = _mem.batt_cal1/10.0
        radio_setting = RadioSetting("batt_cal1", "Trheshold Full (Volt)",
                          RadioSettingValueString(0, 3, str(batt_cal1)))
        radio_setting_group.append(radio_setting)

        batt_cal2 = _mem.batt_cal2/10.0
        radio_setting = RadioSetting("batt_cal2", "Trheshold 4° bar (Volt)",
                          RadioSettingValueString(0, 3, str(batt_cal2)))
        radio_setting_group.append(radio_setting)

        batt_cal3 = _mem.batt_cal3/10.0
        radio_setting = RadioSetting("batt_cal3", "Trheshold 3° bar (Volt)",
                          RadioSettingValueString(0, 3, str(batt_cal3)))
        radio_setting_group.append(radio_setting)

        batt_cal4 = _mem.batt_cal4/10.0
        radio_setting = RadioSetting("batt_cal4", "Trheshold 2° bar (Volt)",
                          RadioSettingValueString(0, 3, str(batt_cal4)))
        radio_setting_group.append(radio_setting)

        batt_cal5 = _mem.batt_cal5/10.0
        radio_setting = RadioSetting("batt_cal5", "Trheshold 1° bar (Volt)",
                          RadioSettingValueString(0, 3, str(batt_cal5)))
        radio_setting_group.append(radio_setting)
        
        batt_cal6 = _mem.batt_cal6/10.0
        radio_setting = RadioSetting("batt_cal6", "Trheshold Empty (Volt)",
                          RadioSettingValueString(0, 3, str(batt_cal6)))
        radio_setting_group.append(radio_setting)

        #_______________________________________________________________________________

        radio_setting_group = RadioSettingGroup("other_calibration", "FrqCal")
        calibration.append(radio_setting_group)

        name = "cal.xtalFreq"
        temp_val = min_max_def(_mem.get_path(name), -50, 50, 0)
        val = RadioSettingValueInteger(-50, 50, temp_val)
        radio_setting = RadioSetting(name, "Xtal frequency correction ,value -50 to +50", val)
        radio_setting_group.append(radio_setting)

        radio_setting_group = RadioSettingGroup("tx_power_calibration",
                                                "TxpCal")
        calibration.append(radio_setting_group)

        for bnd in range(0, 7):
            band_group = RadioSettingSubGroup('txpower_band_%i' % bnd,
                                              'Band %i' % (bnd+1)+(BANDSTX_CAL[bnd]) )
            powers = {"low": "Low", "mid": "Medium", "hi": "High"}
            radio_setting_group.append(band_group)
            for pwr, pwrn in powers.items():
                bounds = ["lower", "center", "upper"]
                subgroup = RadioSettingSubGroup('txpower_band_%i_%s' % (
                    bnd, pwr), pwrn)
                band_group.append(subgroup)
                for bound in bounds:
                    name = f"cal.txp[{bnd}].{pwr}.{bound}"
                    tempval = min_max_def(_mem.get_path(name), 0, 255, 0)
                    val = RadioSettingValueInteger(0, 255, tempval)
                    radio_setting = RadioSetting(name, bound.capitalize(), val)
                    subgroup.append(radio_setting)        

        


        radio_setting_group = RadioSettingGroup("squelch_calibration",
                                                "Squelch")
        calibration.append(radio_setting_group)

        bands = {"sqlBand1_3": "Frequency Band 1-3 (13 ~ 174 MHz)",
                 "sqlBand4_7": "Frequency Band 4-7 (174 ~ 1300 MHz)"}
        for bnd, bndn in bands.items():
            band_group_range = RadioSettingSubGroup(bnd, bndn)
            radio_setting_group.append(band_group_range)
            for sql in range(1, 10):
                band_group = RadioSettingSubGroup(
                    '%s_%i' % (bnd, sql),
                    "Squelch %i" % sql)
                band_group_range.append(band_group)

                name = "cal.%s.openGlitchThr[%i]" % (bnd, sql)
                tempval = min_max_def(_mem.get_path(name), 0, 255, 0)
                val = RadioSettingValueInteger(0, 255, tempval)
                radio_setting = RadioSetting(name, "Glitch threshold open", val)
                band_group.append(radio_setting)

                # name = "cal.%s.closeGlitchThr[%i]" % (bnd, sql)
                # tempval = min_max_def(_mem.get_path(name), 0, 255, 0)
                # val = RadioSettingValueInteger(0, 255, tempval)
                # radio_setting = RadioSetting(name, "Glitch threshold close", val)
                # band_group.append(radio_setting)

                name = "cal.%s.openNoiseThr[%i]" % (bnd, sql)
                tempval = min_max_def(_mem.get_path(name), 0, 127, 0)
                val = RadioSettingValueInteger(0, 127, tempval)
                radio_setting = RadioSetting(name, "Noise threshold open", val)
                band_group.append(radio_setting)

                # name = "cal.%s.closeNoiseThr[%i]" % (bnd, sql)
                # tempval = min_max_def(_mem.get_path(name), 0, 127, 0)
                # val = RadioSettingValueInteger(0, 127, tempval)
                # radio_setting = RadioSetting(name, "Noise threshold close", val)
                # band_group.append(radio_setting)

                name = 'cal.%s.openRssiThr[%i]' % (bnd, sql)
                tempval = min_max_def(_mem.get_path(name), 0, 255, 0)
                val = RadioSettingValueInteger(0, 255, tempval)
                radio_setting = RadioSetting(name, "RSSI threshold open", val)
                band_group.append(radio_setting)

                # name = 'cal.%s.closeRssiThr[%i]' % (bnd, sql)
                # tempval = min_max_def(_mem.get_path(name), 0, 255, 0)
                # val = RadioSettingValueInteger(0, 255, tempval)
                # radio_setting = RadioSetting(name, "RSSI threshold close", val)
                # band_group.append(radio_setting)
        radio_setting_group = RadioSettingGroup("reserved", "reserved")
        calibration.append(radio_setting_group)

        # for lvl in range(0, 10):
            # append_label(radio_setting_group, "_" * 300 , "_" * 300)
            # name = "cal.vox1Thr[%s]" % lvl
            # val = RadioSettingValueInteger(0, 65535, _mem.get_path(name))
            # radio_setting = RadioSetting(name, "Level %i On" % (lvl + 1), val)
            # radio_setting_group.append(radio_setting)

            # name = "cal.vox0Thr[%s]" % lvl
            # val = RadioSettingValueInteger(0, 65535, _mem.get_path(name))
            # radio_setting = RadioSetting(name, "Level %i Off" % (lvl + 1), val)
            # radio_setting_group.append(radio_setting)

           
             



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

            # basic settings

            # Single VFO 
            # if element.get_name() == "single_vfo":
            #     _mem.single_vfo = DUALMODE_LIST.index(str(element.value))
            #     #_mem.single_vfo = element.value and 1 or 0

            # BLMode
            if element.get_name() == "bl_mode":
                _mem.bl_mode = element.value and 1 or 0

            # Inversione display
            if element.get_name() == "back_type":
                _mem.back_type = element.value and 1 or 0

            # RSSI / S Meter 
            if element.get_name() == "signal_meter":
                _mem.signal_meter = element.value and 1 or 0

            # Beep control
            if element.get_name() == "beep_control":
                _mem.beep_control = element.value and 1 or 0

            # VOX switch
            #if element.get_name() == "vox_switch":
            #    _mem.vox_switch = element.value and 1 or 0

            # MicBar
            if element.get_name() == "micbar":
                _mem.micbar = element.value and 1 or 0	

            # Tail tone elimination
            if element.get_name() == "tail_note_elimination":
                _mem.tail_note_elimination = element.value and 1 or 0

            # Key lock
            if element.get_name() == "key_lock":
                _mem.key_lock = element.value and 1 or 0    
                
            # Auto keypad lock
            if element.get_name() == "auto_keypad_lock":
                _mem.auto_keypad_lock = element.value and 1 or 0
                
            # TX Enable
            if element.get_name() == "tx_enable":
                _mem.tx_enable = element.value and 1 or 0

            # VFO open
            if element.get_name() == "vfo_lock":
                _mem.vfo_lock = element.value and 1 or 0

            # Savedirect
            if element.get_name() == "savedirect":              
                _mem.savedirect = element.value and 1 or 0    

            # Satcom
            if element.get_name() == "satcom":              
                _mem.satcom = element.value and 1 or 0

            #---------------------------------------------------

            # call channel
            if element.get_name() == "call_channel":
                _mem.call_channel = int(element.value)-1

            # TOT
            if element.get_name() == "max_talk_time":
                _mem.max_talk_time = TALKTIME_LIST.index(str(element.value))

            # Beacon
            if element.get_name() == "beacon":
                _mem.beacon = BEACON_LIST.index(str(element.value))

            # AFC
            if element.get_name() == "afc":
                _mem.afc = int(element.value)     

            # tx dev
            if element.get_name() == "tx_dev":
                _mem.tx_dev = int(element.value)    

            # vox level
            #if element.get_name() == "vox_level":
            #    _mem.vox_level = int(element.value)-1

            # mic gain
            if element.get_name() == "mic_gain":
                _mem.mic_gain = MICGAIN_LIST.index(str(element.value))

            # Channel display mode    
            if element.get_name() == "channel_display_mode": 
                _mem.channel_display_mode = CHANNELDISP_LIST.index(str(element.value))

            # Backlight auto mode
            if element.get_name() == "backlight_auto_mode":
                _mem.backlight_auto_mode = BACKLIGHT_LIST.index(str(element.value))

            # Power on display mode
            if element.get_name() == "welcome_mode":
                _mem.power_on_dispmode = WELCOME_LIST.index(str(element.value))

            # Repeater tail tone elimination
            if element.get_name() == "repeater_tail_elimination":
                _mem.repeater_tail_elimination = RTE_LIST.index(str(element.value))

            # Crossband receiving/transmitting          
            if element.get_name() == "vfomode":
                 _mem.vfomode = VFOMODE_LIST.index(str(element.value))

            # Dual watch
            # if element.get_name() == "dualwatch":
            #     _mem.dual_watch = DUALWATCH_LIST.index(str(element.value))    

            # Band TX
            if element.get_name() == "bands_tx":
                _mem.bands_tx = BANDS_TX_LIST.index(str(element.value))

            # Battery save
            if element.get_name() == "battery_save":
                _mem.battery_save = BATSAVE_LIST.index(str(element.value))

            # Scan resume mode
            if element.get_name() == "scan_resume_mode":
                 _mem.scan_resume_mode = SCANRESUME_LIST.index(str(element.value))

            # QRZ label    
            if element.get_name() == "qrz_label":
                _mem.qrz_label = element.value

            # Logo string 1
            if element.get_name() == "logo1":
                _mem.logo_line1 = element.value

            # Logo string 2
            if element.get_name() == "logo2":
                _mem.logo_line2 = element.value 

            # Upconv
            if element.get_name() == "upconv":
                _mem.upconv = UPCONV_LIST.index(str(element.value))

            #Custom Frequency Upconverter  
            if element.get_name() == "custom_upconv":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 999.99999*100000.0:
                        val2 = 0x00000000
                       
                    _mem.custom_upconv = val2     

            #Custom tone 
            if element.get_name() == "custom_tone":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*10)
                    except Exception:
                        val2 = 0x09F6

                    if val2 > CTMAX*10:
                        val2 = 0x09F6
                       
                    _mem.custom_tone = val2    
                
           # Sat Frequency Switch  
            if element.get_name() == "sat_freq":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x1AB3F00

                    if val2 > 290.00000*100000.0 or val2 < 210.00000*100000.0:
                        val2 = 0x1AB3F00

                    _mem.sat_freq = val2

            # Battery Calibration   
            if element.get_name() == "batt_cal0":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100)
                    except Exception:
                        val2 = 0xc8

                    if val2 > 2*100:
                        val2 = 0xc8
                       
                    _mem.batt_cal0 = val2   

            if element.get_name() == "batt_cal1":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*10)
                    except Exception:
                        val2 = 0x50

                    if val2 > 9*10:
                        val2 = 0x50
                       
                    _mem.batt_cal1 = val2           

            if element.get_name() == "batt_cal2":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*10)
                    except Exception:
                        val2 = 0x4e

                    if val2 > 9*10:
                        val2 = 0x4e
                       
                    _mem.batt_cal2 = val2 

            if element.get_name() == "batt_cal3":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*10)
                    except Exception:
                        val2 = 0x4b

                    if val2 > 9*10:
                        val2 = 0x4b
                       
                    _mem.batt_cal3 = val2   

            if element.get_name() == "batt_cal4":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*10)
                    except Exception:
                        val2 = 0x48

                    if val2 > 9*10:
                        val2 = 0x48
                       
                    _mem.batt_cal4 = val2    

            if element.get_name() == "batt_cal5":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*10)
                    except Exception:
                        val2 = 0x44

                    if val2 > 9*10:
                        val2 = 0x44
                       
                    _mem.batt_cal5 = val2   

            if element.get_name() == "batt_cal6":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*10)
                    except Exception:
                        val2 = 0x41

                    if val2 > 9*10:
                        val2 = 0x41
                       
                    _mem.batt_cal6 = val2                                                       
                 


            # dtmf settings
            if element.get_name() == "dtmf_side_tone":
                _mem.dtmf_settings.side_tone = \
                        element.value and 1 or 0

            if element.get_name() == "dtmf_separate_code":
                 _mem.dtmf_settings.separate_code = str(element.value)

            if element.get_name() == "group_call_code":
                 _mem.dtmf_settings.group_call_code = str(element.value)

            if element.get_name() == "dtmf_decode_response":
                _mem.dtmf_settings.decode_response = \
                        DTMF_DECODE_RESPONSE_LIST.index(str(element.value))

            if element.get_name() == "dtmf_auto_reset_time":
                _mem.dtmf_settings.auto_reset_time = \
                        int(element.value)

            if element.get_name() == "dtmf_preload_time":
                _mem.dtmf_settings.preload_time = \
                        int(int(element.value)/10)
                
            if element.get_name() == "dtmf_first_code_persist_time":
                _mem.dtmf_settings.first_code_persist_time = \
                        int(int(element.value)/10)
                
            if element.get_name() == "dtmf_hash_persist_time":
                _mem.dtmf_settings.hash_persist_time = \
                        int(int(element.value)/10)

            if element.get_name() == "dtmf_code_persist_time":
                _mem.dtmf_settings.code_persist_time = \
                        int(int(element.value)/10)

            if element.get_name() == "dtmf_code_interval_time":
                _mem.dtmf_settings.code_interval_time = \
                        int(int(element.value)/10)

            if element.get_name() == "dtmf_dtmf_local_code":
                k = str(element.value).rstrip("\x20\xff\x00") + "\x00"*8 
                _mem.dtmf_settings_numbers.dtmf_local_code = k[0:8]

            if element.get_name() == "dtmf_dtmf_up_code":
                k = str(element.value).strip("\x20\xff\x00") + "\x00"*8
                _mem.dtmf_settings_numbers.dtmf_up_code = k[0:8]

            if element.get_name() == "dtmf_dtmf_down_code":
                k = str(element.value).rstrip("\x20\xff\x00") + "\x00"*8
                _mem.dtmf_settings_numbers.dtmf_down_code = k[0:8]

            if element.get_name() == "user_code_ms":
                _mem.user_code_ms = int(element.value)


            # USER CODE 5 Tone List
            if element.get_name() == "user_code0":
                _mem.user_code0 = int(element.value)
            if element.get_name() == "user_code1":
                _mem.user_code1 = int(element.value)
            if element.get_name() == "user_code2":
                _mem.user_code2 = int(element.value)
            if element.get_name() == "user_code3":
                _mem.user_code3 = int(element.value)
            if element.get_name() == "user_code4":
                _mem.user_code4 = int(element.value)
            if element.get_name() == "user_code5":
                _mem.user_code5 = int(element.value)
            if element.get_name() == "user_code6":
                _mem.user_code6 = int(element.value)
            if element.get_name() == "user_code7":
                _mem.user_code7 = int(element.value)
            if element.get_name() == "user_code8":
                _mem.user_code8 = int(element.value)
            if element.get_name() == "user_code9":
                _mem.user_code9 = int(element.value)
            if element.get_name() == "user_codeA":
                _mem.user_codeA = int(element.value)
            if element.get_name() == "user_codeB":
                _mem.user_codeB = int(element.value)
            if element.get_name() == "user_codeC":
                _mem.user_codeC = int(element.value)
            if element.get_name() == "user_codeD":
                _mem.user_codeD = int(element.value)
            if element.get_name() == "user_codeE":
                _mem.user_codeE = int(element.value)
            if element.get_name() == "user_codeF":
                _mem.user_codeF = int(element.value)
                

            # DTMF/5tone Live
            if element.get_name() == "dtmf_live":
                _mem.dtmf_live = DLIVE_LIST.index(str(element.value))    

            

            # dtmf contacts
            for i in range(1, 17):
                varname = "DTMF_" + str(i)
                if element.get_name() == varname:
                    k = str(element.value).rstrip("\x20\xff\x00") + "\x00"*8
                    _mem.dtmfcontact[i-1].name = k[0:8]

                varnumname = "DTMFNUM_" + str(i)
                if element.get_name() == varnumname:
                    k = str(element.value).rstrip("\x20\xff\x00") + "\xff"*8
                    _mem.dtmfcontact[i-1].number = k[0:8]




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

            #--------------------------------------------------- KEYS
            # Key 1 short
            if element.get_name() == "key1_shortpress_action":
                _mem.key1_shortpress_action = element.value

            # Key 2 short
            if element.get_name() == "key2_shortpress_action":
                _mem.key2_shortpress_action = element.value

            # Key 1 long
            if element.get_name() == "key1_longpress_action":
                _mem.key1_longpress_action = element.value

            # Key 1 long
            if element.get_name() == "key2_longpress_action":
                _mem.key2_longpress_action = element.value
            #Calibration
            if element.get_name() == "upload_calibration":
                 self._upload_calibration = bool(element.value)

            if element.changed() and element.get_name().startswith("cal."):
                _mem.get_path(element.get_name()).set_value(element.value)    

            #--------------------------------------------------- PRESET
            if element.get_name() == "Preset_Name_1":
                _mem.preset[0].name = element.value
            if element.get_name() == "Preset_Name_2":
                _mem.preset[1].name = element.value
            if element.get_name() == "Preset_Name_3":
                _mem.preset[2].name = element.value
            if element.get_name() == "Preset_Name_4":
                _mem.preset[3].name = element.value
            if element.get_name() == "Preset_Name_5":
                _mem.preset[4].name = element.value
            if element.get_name() == "Preset_Name_6":
                _mem.preset[5].name = element.value
            if element.get_name() == "Preset_Name_7":
                _mem.preset[6].name = element.value
            if element.get_name() == "Preset_Name_8":
                _mem.preset[7].name = element.value
            if element.get_name() == "Preset_Name_9":
                _mem.preset[8].name = element.value
            if element.get_name() == "Preset_Name_10":
                _mem.preset[9].name = element.value
            if element.get_name() == "Preset_Name_11":
                _mem.preset[10].name = element.value
            if element.get_name() == "Preset_Name_12":
                _mem.preset[11].name = element.value



            if element.get_name() == "Low_Range_1":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[0].freq_low = val2
            if element.get_name() == "Low_Range_2":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[1].freq_low = val2 
            if element.get_name() == "Low_Range_3":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[2].freq_low = val2 
            if element.get_name() == "Low_Range_4":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[3].freq_low = val2 
            if element.get_name() == "Low_Range_5":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[4].freq_low = val2
            if element.get_name() == "Low_Range_6":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[5].freq_low = val2 
            if element.get_name() == "Low_Range_7":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[6].freq_low = val2 
            if element.get_name() == "Low_Range_8":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[7].freq_low = val2 
            if element.get_name() == "Low_Range_9":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[8].freq_low = val2
            if element.get_name() == "Low_Range_10":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[9].freq_low = val2
            if element.get_name() == "Low_Range_11":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[10].freq_low = val2
            if element.get_name() == "Low_Range_12":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[11].freq_low = val2



            if element.get_name() == "Up_Range_1":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[0].freq_up = val2
            if element.get_name() == "Up_Range_2":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[1].freq_up = val2 
            if element.get_name() == "Up_Range_3":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[2].freq_up = val2 
            if element.get_name() == "Up_Range_4":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[3].freq_up = val2 
            if element.get_name() == "Up_Range_5":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[4].freq_up = val2
            if element.get_name() == "Up_Range_6":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[5].freq_up = val2 
            if element.get_name() == "Up_Range_7":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[6].freq_up = val2 
            if element.get_name() == "Up_Range_8":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[7].freq_up = val2 
            if element.get_name() == "Up_Range_9":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[8].freq_up = val2
            if element.get_name() == "Up_Range_10":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[9].freq_up = val2   
            if element.get_name() == "Up_Range_11":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[10].freq_up = val2   
            if element.get_name() == "Up_Range_12":
                    val = str(element.value).strip()
                    try:
                        val2 = round(float(val)*100000.0)
                    except Exception:
                        val2 = 0x00000000

                    if val2 > 1300.00000*100000.0:
                        val2 = 0x00000000
                    _mem.preset[11].freq_up = val2



            if element.get_name() == "Step_1":
                _mem.preset[0].step = STEP_LIST.index(str(element.value))
            if element.get_name() == "Step_2":
                _mem.preset[1].step = STEP_LIST.index(str(element.value))
            if element.get_name() == "Step_3":
                _mem.preset[2].step = STEP_LIST.index(str(element.value))
            if element.get_name() == "Step_4":
                _mem.preset[3].step = STEP_LIST.index(str(element.value))
            if element.get_name() == "Step_5":
                _mem.preset[4].step = STEP_LIST.index(str(element.value))
            if element.get_name() == "Step_6":
                _mem.preset[5].step = STEP_LIST.index(str(element.value))
            if element.get_name() == "Step_7":
                _mem.preset[6].step = STEP_LIST.index(str(element.value))
            if element.get_name() == "Step_8":
                _mem.preset[7].step = STEP_LIST.index(str(element.value))
            if element.get_name() == "Step_9":
                _mem.preset[8].step = STEP_LIST.index(str(element.value))
            if element.get_name() == "Step_10":
                _mem.preset[9].step = STEP_LIST.index(str(element.value))
            if element.get_name() == "Step_11":
                _mem.preset[10].step = STEP_LIST.index(str(element.value))
            if element.get_name() == "Step_12":
                _mem.preset[11].step = STEP_LIST.index(str(element.value))


            if element.get_name() == "TX Power_1":
                _mem.preset[0].txpower = TXPOWER_LIST.index(str(element.value))
            if element.get_name() == "TX Power_2":
                _mem.preset[1].txpower = TXPOWER_LIST.index(str(element.value))
            if element.get_name() == "TX Power_3":
                _mem.preset[2].txpower = TXPOWER_LIST.index(str(element.value))
            if element.get_name() == "TX Power_4":
                _mem.preset[3].txpower = TXPOWER_LIST.index(str(element.value))
            if element.get_name() == "TX Power_5":
                _mem.preset[4].txpower = TXPOWER_LIST.index(str(element.value))
            if element.get_name() == "TX Power_6":
                _mem.preset[5].txpower = TXPOWER_LIST.index(str(element.value))
            if element.get_name() == "TX Power_7":
                _mem.preset[6].txpower = TXPOWER_LIST.index(str(element.value))
            if element.get_name() == "TX Power_8":
                _mem.preset[7].txpower = TXPOWER_LIST.index(str(element.value)) 
            if element.get_name() == "TX Power_9":
                _mem.preset[8].txpower = TXPOWER_LIST.index(str(element.value))
            if element.get_name() == "TX Power_10":
                _mem.preset[9].txpower = TXPOWER_LIST.index(str(element.value))
            if element.get_name() == "TX Power_11":
                _mem.preset[10].txpower = TXPOWER_LIST.index(str(element.value))
            if element.get_name() == "TX Power_12":
                _mem.preset[11].txpower = TXPOWER_LIST.index(str(element.value))                           

            if element.get_name() == "Bw_1":
                _mem.preset[0].bw = BANDWIDTH_LIST.index(str(element.value))
            if element.get_name() == "Bw_2":
                _mem.preset[1].bw = BANDWIDTH_LIST.index(str(element.value))
            if element.get_name() == "Bw_3":
                _mem.preset[2].bw = BANDWIDTH_LIST.index(str(element.value))
            if element.get_name() == "Bw_4":
                _mem.preset[3].bw = BANDWIDTH_LIST.index(str(element.value))
            if element.get_name() == "Bw_5":
                _mem.preset[4].bw = BANDWIDTH_LIST.index(str(element.value))
            if element.get_name() == "Bw_6":
                _mem.preset[5].bw = BANDWIDTH_LIST.index(str(element.value))
            if element.get_name() == "Bw_7":
                _mem.preset[6].bw = BANDWIDTH_LIST.index(str(element.value))
            if element.get_name() == "Bw_8":
                _mem.preset[7].bw = BANDWIDTH_LIST.index(str(element.value))
            if element.get_name() == "Bw_9":
                _mem.preset[8].bw = BANDWIDTH_LIST.index(str(element.value))
            if element.get_name() == "Bw_10":
                _mem.preset[9].bw = BANDWIDTH_LIST.index(str(element.value))
            if element.get_name() == "Bw_11":
                _mem.preset[10].bw = BANDWIDTH_LIST.index(str(element.value))
            if element.get_name() == "Bw_12":
                _mem.preset[11].bw = BANDWIDTH_LIST.index(str(element.value))
                
            if element.get_name() == "AGC_1":
                _mem.preset[0].agcmode = AGC_MODE.index(str(element.value))
            if element.get_name() == "AGC_2":
                _mem.preset[1].agcmode = AGC_MODE.index(str(element.value))
            if element.get_name() == "AGC_3":
                _mem.preset[2].agcmode = AGC_MODE.index(str(element.value))
            if element.get_name() == "AGC_4":
                _mem.preset[3].agcmode = AGC_MODE.index(str(element.value))
            if element.get_name() == "AGC_5":
                _mem.preset[4].agcmode = AGC_MODE.index(str(element.value))
            if element.get_name() == "AGC_6":
                _mem.preset[5].agcmode = AGC_MODE.index(str(element.value))
            if element.get_name() == "AGC_7":
                _mem.preset[6].agcmode = AGC_MODE.index(str(element.value))
            if element.get_name() == "AGC_8":
                _mem.preset[7].agcmode = AGC_MODE.index(str(element.value))
            if element.get_name() == "AGC_9":
                _mem.preset[8].agcmode = AGC_MODE.index(str(element.value))
            if element.get_name() == "AGC_10":
                _mem.preset[9].agcmode = AGC_MODE.index(str(element.value))
            if element.get_name() == "AGC_11":
                _mem.preset[10].agcmode = AGC_MODE.index(str(element.value))
            if element.get_name() == "AGC_12":
                _mem.preset[11].agcmode = AGC_MODE.index(str(element.value))                

            if element.get_name() == "Mode_1":
                _mem.preset[0].modulation = MODULATION_LIST.index(str(element.value))
            if element.get_name() == "Mode_2":
                _mem.preset[1].modulation = MODULATION_LIST.index(str(element.value))
            if element.get_name() == "Mode_3":
                _mem.preset[2].modulation = MODULATION_LIST.index(str(element.value))
            if element.get_name() == "Mode_4":
                _mem.preset[3].modulation = MODULATION_LIST.index(str(element.value))
            if element.get_name() == "Mode_5":
                _mem.preset[4].modulation = MODULATION_LIST.index(str(element.value))
            if element.get_name() == "Mode_6":
                _mem.preset[5].modulation = MODULATION_LIST.index(str(element.value))
            if element.get_name() == "Mode_7":
                _mem.preset[6].modulation = MODULATION_LIST.index(str(element.value))
            if element.get_name() == "Mode_8":
                _mem.preset[7].modulation = MODULATION_LIST.index(str(element.value))
            if element.get_name() == "Mode_9":
                _mem.preset[8].modulation = MODULATION_LIST.index(str(element.value))
            if element.get_name() == "Mode_10":
                _mem.preset[9].modulation = MODULATION_LIST.index(str(element.value))
            if element.get_name() == "Mode_11":
                _mem.preset[10].modulation = MODULATION_LIST.index(str(element.value))
            if element.get_name() == "Mode_12":
                _mem.preset[11].modulation = MODULATION_LIST.index(str(element.value))

            if element.get_name() == "Sql_1":
                _mem.preset[0].squelch = SQUELCH_LIST.index(str(element.value))
            if element.get_name() == "Sql_2":
                _mem.preset[1].squelch = SQUELCH_LIST.index(str(element.value))
            if element.get_name() == "Sql_3":
                _mem.preset[2].squelch = SQUELCH_LIST.index(str(element.value))
            if element.get_name() == "Sql_4":
                _mem.preset[3].squelch = SQUELCH_LIST.index(str(element.value))
            if element.get_name() == "Sql_5":
                _mem.preset[4].squelch = SQUELCH_LIST.index(str(element.value))
            if element.get_name() == "Sql_6":
                _mem.preset[5].squelch = SQUELCH_LIST.index(str(element.value))
            if element.get_name() == "Sql_7":
                _mem.preset[6].squelch = SQUELCH_LIST.index(str(element.value))
            if element.get_name() == "Sql_8":
                _mem.preset[7].squelch = SQUELCH_LIST.index(str(element.value))
            if element.get_name() == "Sql_9":
                _mem.preset[8].squelch = SQUELCH_LIST.index(str(element.value))
            if element.get_name() == "Sql_10":
                _mem.preset[9].squelch = SQUELCH_LIST.index(str(element.value))
            if element.get_name() == "Sql_11":
                _mem.preset[10].squelch = SQUELCH_LIST.index(str(element.value))
            if element.get_name() == "Sql_12":
                _mem.preset[11].squelch = SQUELCH_LIST.index(str(element.value))

            # Memory Speed
            # if element.get_name() == "mem_speed":
            #    _mem.mem_speed = 6 + MEMSPEED_LIST.index(str(element.value))