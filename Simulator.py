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


def sign_extend(value, bits):
    if value & (1 << (bits - 1)):
        value -= (1 << bits)
    return value


def extract_bits(value, hi, lo):
    return (value >> lo) & ((1 << (hi - lo + 1)) - 1)


def to_bin32(x):
    return "0b" + format(u32(x), "032b")


class Memory:
    def __init__(self):
        self.instructions = []
        self.data = {}
        self.stack = {}
    
    def load_program(self, instructions):
        self.instructions = instructions[:]

    def read_instr(self, pc):
        if pc % 4 != 0:
            raise SimulationError("Instruction fetch from unaligned PC")
        index = pc // 4
        if index < 0 or index >= len(self.instructions):
            raise SimulationError("PC out of instruction memory range")
        return self.instructions[index]

    def _is_valid_address(self, address):
        if address % 4 != 0:
            return False

        in_data = DATA_MEM_BASE <= address <= DATA_MEM_END
        in_stack = STACK_BASE <= address <= STACK_END
        return in_data or in_stack

    def lw(self, address):
        address = u32(address)

        if not self._is_valid_address(address):
            raise SimulationError("Invalid memory access")

        if STACK_BASE <= address <= STACK_END:
            return self.stack.get(address, 0)
        return self.data.get(address, 0)

    def sw(self, address, value):
        address = u32(address)

        if not self._is_valid_address(address):
            raise SimulationError("Invalid memory access")

        if STACK_BASE <= address <= STACK_END:
            self.stack[address] = u32(value)
        else:
            self.data[address] = u32(value)

    def dump_data_memory_lines(self):
        lines = []
        for addr in range(DATA_MEM_BASE, DATA_MEM_END + 1, 4):
            lines.append(f"0x{addr:08X}:{to_bin32(self.data.get(addr, 0))}")
        return lines


class CPU:
    def __init__(self, memory, addr_to_line):
        self.memory = memory
        self.addr_to_line = addr_to_line
        self.regs = [0] * 32
        self.regs[2] = 0x0000017C
        self.pc = 0
        self.trace_lines = []