import sys

MASK32 = 0xFFFFFFFF
DATA_MEM_BASE = 0x00010000
DATA_MEM_WORDS = 32
DATA_MEM_END = DATA_MEM_BASE + 4 * DATA_MEM_WORDS - 4

# 🔥 Toggle this
DEBUG = False


class SimulationError(Exception):
    pass


def debug_print(msg):
    if DEBUG:
        print(msg)


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

    def load_program(self, instructions):
        self.instructions = instructions[:]

    def read_instr(self, pc):
        if pc % 4 != 0:
            raise SimulationError("Instruction fetch from unaligned PC")
        index = pc // 4
        if index < 0 or index >= len(self.instructions):
            raise SimulationError("PC out of instruction memory range")
        return self.instructions[index]

    def _check_data_address(self, address):
        if address % 4 != 0:
            raise SimulationError("Unaligned data memory access")
        if address < DATA_MEM_BASE or address > DATA_MEM_END:
            raise SimulationError("Invalid data memory access")

    def lw(self, address):
        address = u32(address)
        self._check_data_address(address)
        return self.data.get(address, 0)

    def sw(self, address, value):
        address = u32(address)
        self._check_data_address(address)
        self.data[address] = u32(value)

    def dump_data_memory_lines(self):
        lines = []
        for addr in range(DATA_MEM_BASE, DATA_MEM_BASE + 4 * DATA_MEM_WORDS, 4):
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
        vals = [to_bin32(self.pc)] + [to_bin32(r) for r in self.regs]
        self.trace_lines.append(" ".join(vals))

    def run(self):
        while True:
            current_pc = self.pc
            instr = self.memory.read_instr(current_pc)

            try:
                halted = self.execute(instr, current_pc)
            except SimulationError as e:
                debug_print(f"Error: {str(e)} at line {self.addr_to_line.get(current_pc, '?')}")
                break

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
            elif funct3 == 0b001:
                self.write_reg(rd, a << (b & 0x1F))
            elif funct3 == 0b010:
                self.write_reg(rd, 1 if s32(a) < s32(b) else 0)
            elif funct3 == 0b011:
                self.write_reg(rd, 1 if u32(a) < u32(b) else 0)
            elif funct3 == 0b100:
                self.write_reg(rd, a ^ b)
            elif funct3 == 0b101:
                self.write_reg(rd, u32(a) >> (b & 0x1F))
            elif funct3 == 0b110:
                self.write_reg(rd, a | b)
            elif funct3 == 0b111:
                self.write_reg(rd, a & b)
            else:
                raise SimulationError("Invalid R-type instruction")

            self.pc = u32(current_pc + 4)
            return False

        # I-type / load / jalr
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
                    raise SimulationError("Invalid I-type instruction")
                self.pc += 4
                return False

            elif opcode == 0b0000011:
                if funct3 != 0b010:
                    raise SimulationError("Invalid load")
                address = u32(a + imm)
                value = self.memory.lw(address)
                self.write_reg(rd, value)
                self.pc += 4
                return False

            else:
                ret_addr = u32(current_pc + 4)
                target = u32(a + imm) & ~1
                self.write_reg(rd, ret_addr)
                self.pc = target
                return False

        # S-type
        elif opcode == 0b0100011:
            rs1 = extract_bits(instr, 19, 15)
            rs2 = extract_bits(instr, 24, 20)
            imm = sign_extend(
                (extract_bits(instr, 31, 25) << 5) | extract_bits(instr, 11, 7), 12
            )
            address = u32(self.read_reg(rs1) + imm)
            self.memory.sw(address, self.read_reg(rs2))
            self.pc += 4
            return False

        # B-type
        elif opcode == 0b1100011:
            rs1 = extract_bits(instr, 19, 15)
            rs2 = extract_bits(instr, 24, 20)

            imm = sign_extend(
                (extract_bits(instr, 31, 31) << 12)
                | (extract_bits(instr, 7, 7) << 11)
                | (extract_bits(instr, 30, 25) << 5)
                | (extract_bits(instr, 11, 8) << 1),
                13,
            )

            if rs1 == 0 and rs2 == 0 and imm == 0:
                return True

            take = self.read_reg(rs1) == self.read_reg(rs2)
            self.pc = current_pc + imm if take else current_pc + 4
            return False

        else:
            raise SimulationError("Unknown opcode")


def run_simulation_from_lines(lines):
    instructions = []
    addr_to_line = {}
    addr = 0

    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        instructions.append(int(line, 2))
        addr_to_line[addr] = line_no
        addr += 4

    memory = Memory()
    memory.load_program(instructions)

    cpu = CPU(memory, addr_to_line)
    cpu.run()

    return cpu.trace_lines, memory.dump_data_memory_lines()


def emit_output(trace_lines, memory_lines, output_file=None):
    lines = trace_lines + memory_lines
    text = "\n".join(lines) + "\n"

    if output_file:
        with open(output_file, "w") as f:
            f.write(text)
    else:
        print(text, end="")


def main():
    lines = sys.stdin.readlines()
    trace_lines, memory_lines = run_simulation_from_lines(lines)
    emit_output(trace_lines, memory_lines)


if __name__ == "__main__":
    main()
