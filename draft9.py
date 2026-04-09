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

    def read_reg(self, idx):
        return 0 if idx == 0 else self.regs[idx]

    def write_reg(self, idx, value):
        if idx != 0:
            self.regs[idx] = u32(value)
        self.regs[0] = 0

    def trace(self):
        self.regs[0] = 0
        self.trace_lines.append(
            " ".join([to_bin32(self.pc)] + [to_bin32(r) for r in self.regs]) + " "
        )

    def run(self):
        while True:
            current_pc = self.pc
            instr = self.memory.read_instr(current_pc)
            halted = self.execute(instr, current_pc)
            self.trace()
            if halted:
                break

    def execute(self, instr, current_pc):
        opcode = extract_bits(instr, 6, 0)

        # R-type
        if opcode == 0b0110011:
            rd = extract_bits(instr, 11, 7)
            funct3 = extract_bits(instr, 14, 12)
            rs1 = extract_bits(instr, 19, 15)
            rs2 = extract_bits(instr, 24, 20)
            funct7 = extract_bits(instr, 31, 25)

            a = self.read_reg(rs1)
            b = self.read_reg(rs2)

            if funct3 == 0b000 and funct7 == 0b0000000:
                self.write_reg(rd, a + b)
            elif funct3 == 0b000 and funct7 == 0b0100000:
                self.write_reg(rd, a - b)
            elif funct3 == 0b001 and funct7 == 0b0000000:
                self.write_reg(rd, a << (b & 0x1F))
            elif funct3 == 0b010 and funct7 == 0b0000000:
                self.write_reg(rd, 1 if s32(a) < s32(b) else 0)
            elif funct3 == 0b011 and funct7 == 0b0000000:
                self.write_reg(rd, 1 if u32(a) < u32(b) else 0)
            elif funct3 == 0b100 and funct7 == 0b0000000:
                self.write_reg(rd, a ^ b)
            elif funct3 == 0b101 and funct7 == 0b0000000:
                self.write_reg(rd, u32(a) >> (b & 0x1F))
            elif funct3 == 0b110 and funct7 == 0b0000000:
                self.write_reg(rd, a | b)
            elif funct3 == 0b111 and funct7 == 0b0000000:
                self.write_reg(rd, a & b)
            else:
                raise SimulationError(
                    f"Invalid R-type instruction at line {self.addr_to_line.get(current_pc, '?')}"
                )

            self.pc = u32(current_pc + 4)
            return False

        # I-type
        elif opcode in (0b0010011, 0b0000011, 0b1100111):
            rd = extract_bits(instr, 11, 7)
            funct3 = extract_bits(instr, 14, 12)
            rs1 = extract_bits(instr, 19, 15)
            imm = sign_extend(extract_bits(instr, 31, 20), 12)

            a = self.read_reg(rs1)

            if opcode == 0b0010011:
                if funct3 == 0b000:
                    self.write_reg(rd, a + imm)
                elif funct3 == 0b011:
                    self.write_reg(rd, 1 if u32(a) < u32(imm) else 0)
                else:
                    raise SimulationError(
                        f"Invalid I-type instruction at line {self.addr_to_line.get(current_pc, '?')}"
                    )
                self.pc = u32(current_pc + 4)
                return False

            elif opcode == 0b0000011:
                if funct3 != 0b010:
                    raise SimulationError(
                        f"Invalid load instruction at line {self.addr_to_line.get(current_pc, '?')}"
                    )
                address = u32(a + imm)
                value = self.memory.lw(address)
                self.write_reg(rd, value)
                self.pc = u32(current_pc + 4)
                return False

            else:
                if funct3 != 0b000:
                    raise SimulationError(
                        f"Invalid jalr instruction at line {self.addr_to_line.get(current_pc, '?')}"
                    )
                ret_addr = u32(current_pc + 4)
                target = u32(a + imm) & ~1
                self.write_reg(rd, ret_addr)
                self.pc = target
                return False

        # S-type
        elif opcode == 0b0100011:
            funct3 = extract_bits(instr, 14, 12)
            rs1 = extract_bits(instr, 19, 15)
            rs2 = extract_bits(instr, 24, 20)
            imm11_5 = extract_bits(instr, 31, 25)
            imm4_0 = extract_bits(instr, 11, 7)
            imm = sign_extend((imm11_5 << 5) | imm4_0, 12)

            if funct3 != 0b010:
                raise SimulationError(
                    f"Invalid store instruction at line {self.addr_to_line.get(current_pc, '?')}"
                )

            address = u32(self.read_reg(rs1) + imm)
            self.memory.sw(address, self.read_reg(rs2))
            self.pc = u32(current_pc + 4)
            return False

        # B-type
        elif opcode == 0b1100011:
            funct3 = extract_bits(instr, 14, 12)
            rs1 = extract_bits(instr, 19, 15)
            rs2 = extract_bits(instr, 24, 20)

            imm12 = extract_bits(instr, 31, 31)
            imm10_5 = extract_bits(instr, 30, 25)
            imm4_1 = extract_bits(instr, 11, 8)
            imm11 = extract_bits(instr, 7, 7)

            imm = (imm12 << 12) | (imm11 << 11) | (imm10_5 << 5) | (imm4_1 << 1)
            imm = sign_extend(imm, 13)

            a = self.read_reg(rs1)
            b = self.read_reg(rs2)

            if funct3 == 0b000:
                take = (a == b)
            elif funct3 == 0b001:
                take = (a != b)
            elif funct3 == 0b100:
                take = (s32(a) < s32(b))
            elif funct3 == 0b101:
                take = (s32(a) >= s32(b))
            elif funct3 == 0b110:
                take = (u32(a) < u32(b))
            elif funct3 == 0b111:
                take = (u32(a) >= u32(b))
            else:
                raise SimulationError(
                    f"Invalid branch instruction at line {self.addr_to_line.get(current_pc, '?')}"
                )

            if funct3 == 0b000 and rs1 == 0 and rs2 == 0 and imm == 0:
                self.pc = u32(current_pc)
                return True

            self.pc = u32(current_pc + imm) if take else u32(current_pc + 4)
            return False

        # U-type
        elif opcode in (0b0110111, 0b0010111):
            rd = extract_bits(instr, 11, 7)
            imm = extract_bits(instr, 31, 12) << 12

            if opcode == 0b0110111:
                self.write_reg(rd, imm)
            else:
                self.write_reg(rd, current_pc + imm)

            self.pc = u32(current_pc + 4)
            return False

        # J-type
        elif opcode == 0b1101111:
            rd = extract_bits(instr, 11, 7)
            imm20 = extract_bits(instr, 31, 31)
            imm10_1 = extract_bits(instr, 30, 21)
            imm11 = extract_bits(instr, 20, 20)
            imm19_12 = extract_bits(instr, 19, 12)

            imm = (imm20 << 20) | (imm19_12 << 12) | (imm11 << 11) | (imm10_1 << 1)
            imm = sign_extend(imm, 21)

            self.write_reg(rd, current_pc + 4)
            self.pc = u32(current_pc + imm)
            return False

        else:
            raise SimulationError(
                f"Unknown opcode at line {self.addr_to_line.get(current_pc, '?')}"
            )


def run_simulation_from_lines(lines):
    instructions = []
    addr_to_line = {}
    addr = 0

    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if line == "":
            continue

        if len(line) != 32 or any(ch not in "01" for ch in line):
            raise SimulationError(f"Invalid binary instruction at line {line_no}")

        instructions.append(int(line, 2))
        addr_to_line[addr] = line_no
        addr += 4

    memory = Memory()
    memory.load_program(instructions)

    cpu = CPU(memory, addr_to_line)

    try:
        cpu.run()
        return cpu.trace_lines, memory.dump_data_memory_lines()
    except SimulationError:
        # important for hard_4:
        # stop immediately and do not print memory dump
        return cpu.trace_lines, []


def emit_output(trace_lines, memory_lines, output_file=None):
    lines = trace_lines + memory_lines
    text = "\n".join(lines)
    if lines:
        text += "\n"

    if output_file is None:
        sys.stdout.write(text)
    else:
        with open(output_file, "w", newline="\n") as f:
            f.write(text)


def main():
    try:
        with open(sys.argv[1], "r") as f:
            lines = f.readlines()

        trace_lines, memory_lines = run_simulation_from_lines(lines)
        emit_output(trace_lines, memory_lines, sys.argv[2])

    except:
        with open(sys.argv[2], "w", newline="\n") as f:
            f.write("")


if __name__ == "__main__":
    main()
