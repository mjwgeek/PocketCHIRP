#pragma once
#include <stdint.h>

#define PC_BRIDGE_PROTOCOL_VERSION 2
#define PC_BRIDGE_NAME "PocketCHIRP Field Programmer"
#define PC_UUID_SERVICE_STR "8f6a2c50-3d47-4b72-9a31-50ce6b7d1000"
#define PC_UUID_DATA_TX_STR "8f6a2c51-3d47-4b72-9a31-50ce6b7d1000"
#define PC_UUID_DATA_RX_STR "8f6a2c52-3d47-4b72-9a31-50ce6b7d1000"
#define PC_UUID_CONTROL_STR "8f6a2c53-3d47-4b72-9a31-50ce6b7d1000"
#define PC_UUID_FILE_STR    "8f6a2c54-3d47-4b72-9a31-50ce6b7d1000"

enum pc_cmd : uint8_t {
    PC_CMD_HELLO         = 0x01,
    PC_CMD_START_SESSION = 0x02,
    PC_CMD_SET_LINE      = 0x03,
    PC_CMD_SET_DTR       = 0x04,
    PC_CMD_SET_RTS       = 0x05,
    PC_CMD_END_SESSION   = 0x06,
    PC_CMD_GET_STATUS    = 0x07,
    PC_CMD_USB_REOPEN    = 0x08,
};

enum pc_status : uint8_t {
    PC_ST_OK         = 0x00,
    PC_ST_BAD_CMD    = 0x01,
    PC_ST_BAD_LENGTH = 0x02,
    PC_ST_NO_USB     = 0x03,
    PC_ST_USB_ERROR  = 0x04,
    PC_ST_QUEUE_FULL = 0x05,
};

struct __attribute__((packed)) pc_line_request {
    uint32_t baud;
    uint8_t data_bits;
    uint8_t stop_bits;
    uint8_t parity;
};
