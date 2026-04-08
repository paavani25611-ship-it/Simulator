import sys
import os


def u32(value):
    return value & 0xFFFFFFFF


def s32(value):
    value &= 0xFFFFFFFF
    if value & 0x80000000:
        return value - (1 << 32)
    return value


def sign_extend(value, bits):
    if value & (1 << (bits - 1)):
        value -= (1 << bits)
    return value


def to_bin32(value):
    return format(value & 0xFFFFFFFF, "032b")


def to_hex8(value):
    return "0x" + format(value & 0xFFFFFFFF, "08x")


def extract_bits(instr, hi, lo):
    mask = (1 << (hi - lo + 1)) - 1
    return (instr >> lo) & mask


def get_r_fields(instr):
    funct7 = extract_bits(instr, 31, 25)
    rs2 = extract_bits(instr, 24, 20)
    rs1 = extract_bits(instr, 19, 15)
    funct3 = extract_bits(instr, 14, 12)
    rd = extract_bits(instr, 11, 7)
    opcode = extract_bits(instr, 6, 0)
    return funct7, rs2, rs1, funct3, rd, opcode


def get_i_fields(instr):
    imm = extract_bits(instr, 31, 20)
    rs1 = extract_bits(instr, 19, 15)
    funct3 = extract_bits(instr, 14, 12)
    rd = extract_bits(instr, 11, 7)
    opcode = extract_bits(instr, 6, 0)
    return imm, rs1, funct3, rd, opcode


def get_s_fields(instr):
    imm11_5 = extract_bits(instr, 31, 25)
    rs2 = extract_bits(instr, 24, 20)
    rs1 = extract_bits(instr, 19, 15)
    funct3 = extract_bits(instr, 14, 12)
    imm4_0 = extract_bits(instr, 11, 7)
    opcode = extract_bits(instr, 6, 0)
    imm = (imm11_5 << 5) | imm4_0
    return imm, rs2, rs1, funct3, opcode


def get_b_fields(instr):
    imm12 = extract_bits(instr, 31, 31)
    imm10_5 = extract_bits(instr, 30, 25)
    rs2 = extract_bits(instr, 24, 20)
    rs1 = extract_bits(instr, 19, 15)
    funct3 = extract_bits(instr, 14, 12)
    imm4_1 = extract_bits(instr, 11, 8)
    imm11 = extract_bits(instr, 7, 7)
    opcode = extract_bits(instr, 6, 0)

    imm = (imm12 << 12) | (imm11 << 11) | (imm10_5 << 5) | (imm4_1 << 1)
    return imm, rs2, rs1, funct3, opcode


def get_u_fields(instr):
    imm31_12 = extract_bits(instr, 31, 12)
    rd = extract_bits(instr, 11, 7)
    opcode = extract_bits(instr, 6, 0)
    return imm31_12, rd, opcode


def get_j_fields(instr):
    imm20 = extract_bits(instr, 31, 31)
    imm10_1 = extract_bits(instr, 30, 21)
    imm11 = extract_bits(instr, 20, 20)
    imm19_12 = extract_bits(instr, 19, 12)
    rd = extract_bits(instr, 11, 7)
    opcode = extract_bits(instr, 6, 0)

    imm = (imm20 << 20) | (imm19_12 << 12) | (imm11 << 11) | (imm10_1 << 1)
    return imm, rd, opcode


class Memory:
    def __init__(self):
        self.program = {}
        self.stack = {}
        self.data = {}

        addr = 0x00000100
        for _ in range(32):
            self.stack[addr] = 0
            addr += 4

        addr = 0x00010000
        for _ in range(32):
            self.data[addr] = 0
            addr += 4

    def load_program(self, instructions):
        addr = 0
        for instr in instructions:
            self.program[addr] = instr
            addr += 4

    def read_word(self, addr):
        if addr % 4 != 0:
            raise ValueError(f"Unaligned memory read at address {to_hex8(addr)}")

        if addr in self.stack:
            return self.stack[addr]
        if addr in self.data:
            return self.data[addr]

        raise ValueError(f"Invalid memory read at address {to_hex8(addr)}")

    def write_word(self, addr, value):
        if addr % 4 != 0:
            raise ValueError(f"Unaligned memory write at address {to_hex8(addr)}")

        if addr in self.stack:
            self.stack[addr] = u32(value)
            return
        if addr in self.data:
            self.data[addr] = u32(value)
            return

        raise ValueError(f"Invalid memory write at address {to_hex8(addr)}")

    def dump_data_memory_lines(self):
        lines = []
        addr = 0x00010000
        for _ in range(32):
            lines.append(f"{to_hex8(addr)}:{to_bin32(self.data[addr])}")
            addr += 4
        return lines


class CPU:
    def __init__(self, memory, addr_to_line):
        self.mem = memory
        self.addr_to_line = addr_to_line
        self.regs = [0] * 32
        self.pc = 0
        self.trace_lines = []
        self.halted = False

        # Stack pointer initial value
        self.regs[2] = 0x0000017C

    def fetch(self):
        if self.pc not in self.mem.program:
            raise ValueError(f"PC out of program memory range at {to_hex8(self.pc)}")
        return self.mem.program[self.pc]

    def write_reg(self, rd, value):
        if rd != 0:
            self.regs[rd] = u32(value)

    def force_x0(self):
        self.regs[0] = 0

    def append_trace(self):
        line = [to_bin32(self.pc)]
        for reg in self.regs:
            line.append(to_bin32(reg))
        self.trace_lines.append(" ".join(line))

    def step(self):
        old_pc = self.pc
        instr = self.fetch()
        opcode = extract_bits(instr, 6, 0)

        # R-type
        if opcode == 0b0110011:
            funct7, rs2, rs1, funct3, rd, _ = get_r_fields(instr)
            a = self.regs[rs1]
            b = self.regs[rs2]

            if funct3 == 0b000 and funct7 == 0b0000000:      # add
                self.write_reg(rd, s32(a) + s32(b))
            elif funct3 == 0b000 and funct7 == 0b0100000:    # sub
                self.write_reg(rd, s32(a) - s32(b))
            elif funct3 == 0b001 and funct7 == 0b0000000:    # sll
                self.write_reg(rd, u32(a << (b & 0x1F)))
            elif funct3 == 0b010 and funct7 == 0b0000000:    # slt
                self.write_reg(rd, 1 if s32(a) < s32(b) else 0)
            elif funct3 == 0b011 and funct7 == 0b0000000:    # sltu
                self.write_reg(rd, 1 if u32(a) < u32(b) else 0)
            elif funct3 == 0b100 and funct7 == 0b0000000:    # xor
                self.write_reg(rd, a ^ b)
            elif funct3 == 0b101 and funct7 == 0b0000000:    # srl
                self.write_reg(rd, u32(a) >> (b & 0x1F))
            elif funct3 == 0b110 and funct7 == 0b0000000:    # or
                self.write_reg(rd, a | b)
            elif funct3 == 0b111 and funct7 == 0b0000000:    # and
                self.write_reg(rd, a & b)
            else:
                raise ValueError("Unsupported R-type instruction")

            self.pc = u32(old_pc + 4)

        # lw
        elif opcode == 0b0000011:
            imm, rs1, funct3, rd, _ = get_i_fields(instr)

            if funct3 != 0b010:
                raise ValueError("Unsupported load instruction")

            imm = sign_extend(imm, 12)
            addr = u32(self.regs[rs1] + imm)
            value = self.mem.read_word(addr)
            self.write_reg(rd, value)
            self.pc = u32(old_pc + 4)

        # addi / sltiu
        elif opcode == 0b0010011:
            imm, rs1, funct3, rd, _ = get_i_fields(instr)
            imm_se = sign_extend(imm, 12)

            if funct3 == 0b000:          # addi
                self.write_reg(rd, s32(self.regs[rs1]) + imm_se)
            elif funct3 == 0b011:        # sltiu
                self.write_reg(rd, 1 if u32(self.regs[rs1]) < u32(imm_se) else 0)
            else:
                raise ValueError("Unsupported I-type arithmetic instruction")

            self.pc = u32(old_pc + 4)

        # jalr
        elif opcode == 0b1100111:
            imm, rs1, funct3, rd, _ = get_i_fields(instr)

            if funct3 != 0b000:
                raise ValueError("Unsupported jalr instruction")

            imm = sign_extend(imm, 12)
            ret_addr = u32(old_pc + 4)
            target = u32(self.regs[rs1] + imm) & 0xFFFFFFFE

            self.write_reg(rd, ret_addr)
            self.pc = target

        # sw
        elif opcode == 0b0100011:
            imm, rs2, rs1, funct3, _ = get_s_fields(instr)

            if funct3 != 0b010:
                raise ValueError("Unsupported store instruction")

            imm = sign_extend(imm, 12)
            addr = u32(self.regs[rs1] + imm)
            self.mem.write_word(addr, self.regs[rs2])
            self.pc = u32(old_pc + 4)

        # branches
        elif opcode == 0b1100011:
            imm, rs2, rs1, funct3, _ = get_b_fields(instr)
            offset = sign_extend(imm, 13)

            a_s = s32(self.regs[rs1])
            b_s = s32(self.regs[rs2])
            a_u = u32(self.regs[rs1])
            b_u = u32(self.regs[rs2])

            # Virtual halt: beq x0, x0, 0
            if funct3 == 0b000 and rs1 == 0 and rs2 == 0 and offset == 0:
                self.pc = old_pc
                self.force_x0()
                self.append_trace()
                self.halted = True
                return

            take = False
            if funct3 == 0b000:      # beq
                take = (a_s == b_s)
            elif funct3 == 0b001:    # bne
                take = (a_s != b_s)
            elif funct3 == 0b100:    # blt
                take = (a_s < b_s)
            elif funct3 == 0b101:    # bge
                take = (a_s >= b_s)
            elif funct3 == 0b110:    # bltu
                take = (a_u < b_u)
            elif funct3 == 0b111:    # bgeu
                take = (a_u >= b_u)
            else:
                raise ValueError("Unsupported branch instruction")

            self.pc = u32(old_pc + offset) if take else u32(old_pc + 4)

        # lui / auipc
        elif opcode == 0b0110111 or opcode == 0b0010111:
            imm31_12, rd, op = get_u_fields(instr)
            imm_value = imm31_12 << 12

            if op == 0b0110111:      # lui
                self.write_reg(rd, imm_value)
            else:                    # auipc
                self.write_reg(rd, u32(old_pc + imm_value))

            self.pc = u32(old_pc + 4)

        # jal
        elif opcode == 0b1101111:
            imm, rd, _ = get_j_fields(instr)
            offset = sign_extend(imm, 21)

            self.write_reg(rd, u32(old_pc + 4))
            self.pc = u32(old_pc + offset) & 0xFFFFFFFE

        else:
            raise ValueError("Unsupported opcode")

        self.force_x0()
        self.append_trace()

    def run(self):
        while not self.halted:
            self.step()


def write_output(path, trace_lines, memory_lines):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "w") as f:
        for line in trace_lines:
            f.write(line + "\n")
        for line in memory_lines:
            f.write(line + "\n")


def parse_binary_lines(lines):
    instructions = []
    addr_to_line = {}
    addr = 0

    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if line == "":
            continue

        if len(line) != 32 or any(ch not in "01" for ch in line):
            raise ValueError(f"Invalid binary instruction at line {line_no}")

        instructions.append(int(line, 2))
        addr_to_line[addr] = line_no
        addr += 4

    return instructions, addr_to_line


def run_simulation_from_lines(lines):
    instructions, addr_to_line = parse_binary_lines(lines)

    memory = Memory()
    memory.load_program(instructions)

    cpu = CPU(memory, addr_to_line)
    cpu.run()

    memory_lines = memory.dump_data_memory_lines()
    return cpu.trace_lines, memory_lines


def try_framework_default_write(trace_lines, memory_lines):
    candidate_paths = [
        "../tests/user_traces/simple/simple_1.txt",
        "../automatedTesting/tests/user_traces/simple/simple_1.txt",
        "tests/user_traces/simple/simple_1.txt",
    ]

    for path in candidate_paths:
        try:
            write_output(path, trace_lines, memory_lines)
            return
        except Exception:
            continue


def main():
    try:
        # stdin mode
        if len(sys.argv) == 1:
            lines = sys.stdin.readlines()
            trace_lines, memory_lines = run_simulation_from_lines(lines)

            for line in trace_lines:
                print(line)
            for line in memory_lines:
                print(line)

            try_framework_default_write(trace_lines, memory_lines)
            return

        # input file only -> print to stdout
        elif len(sys.argv) == 2:
            input_path = sys.argv[1]

            with open(input_path, "r") as f:
                lines = f.readlines()

            trace_lines, memory_lines = run_simulation_from_lines(lines)

            for line in trace_lines:
                print(line)
            for line in memory_lines:
                print(line)
            return

        # input file + output file
        else:
            input_path = sys.argv[1]
            output_path = sys.argv[2]

            with open(input_path, "r") as f:
                lines = f.readlines()

            trace_lines, memory_lines = run_simulation_from_lines(lines)
            write_output(output_path, trace_lines, memory_lines)
            return

    except Exception as e:
        print(str(e))


if __name__ == "__main__":
    main()
