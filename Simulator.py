import sys

MASK32 = 0xFFFFFFFF

DATA_MEM_BASE = 0x00010000
DATA_MEM_WORDS = 32
DATA_MEM_END = DATA_MEM_BASE + 4 * DATA_MEM_WORDS - 4

STACK_BASE = 0x00000100
STACK_END = 0x0000017C


class SimulationError(Exception):
    pass


def u32(x):
    return x & MASK32


def s32(x):
    x &= MASK32
    return x if x < (1 << 31) else x - (1 << 32)
