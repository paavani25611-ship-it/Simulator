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
            raise SimulationError("Error in line ?")
        index = pc // 4
        if index < 0 or index >= len(self.instructions):
            raise SimulationError("Error in line ?")
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
            raise SimulationError("MEMORY_ERROR")
        if STACK_BASE <= address <= STACK_END:
            return self.stack.get(address, 0)
        return self.data.get(address, 0)

    def sw(self, address, value):
        address = u32(address)
        if not self._is_valid_address(address):
            raise SimulationError("MEMORY_ERROR")
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
            " ".join([to_bin32(self.pc)] + [to_bin32(r) for r in self.regs])
        )

    def run(self):
        while True:
            current_pc = self.pc
            instr = self.memory.read_instr(current_pc)

            try:
                halted = self.execute(instr, current_pc)
            except SimulationError:
                raise

            self.trace()

            if halted:
                break

    def execute(self, instr, current_pc):
        opcode = extract_bits(instr, 6, 0)

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
                raise SimulationError(f"Error in line {self.addr_to_line.get(current_pc,'?')}")

            self.pc += 4
            return False

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
                    raise SimulationError(f"Error in line {self.addr_to_line.get(current_pc,'?')}")
                self.pc += 4
                return False

            elif opcode == 0b0000011:
                if funct3 != 0b010:
                    raise SimulationError(f"Error in line {self.addr_to_line.get(current_pc,'?')}")
                try:
                    value = self.memory.lw(a + imm)
                except:
                    raise SimulationError(f"Error in line {self.addr_to_line.get(current_pc,'?')}")
                self.write_reg(rd, value)
                self.pc += 4
                return False

            else:
                if funct3 != 0b000:
                    raise SimulationError(f"Error in line {self.addr_to_line.get(current_pc,'?')}")
                self.write_reg(rd, current_pc + 4)
                self.pc = (a + imm) & ~1
                return False

        elif opcode == 0b0100011:
            funct3 = extract_bits(instr, 14, 12)
            rs1 = extract_bits(instr, 19, 15)
            rs2 = extract_bits(instr, 24, 20)
            imm = sign_extend((extract_bits(instr,31,25)<<5)|extract_bits(instr,11,7),12)

            if funct3 != 0b010:
                raise SimulationError(f"Error in line {self.addr_to_line.get(current_pc,'?')}")

            try:
                self.memory.sw(self.read_reg(rs1)+imm, self.read_reg(rs2))
            except:
                raise SimulationError(f"Error in line {self.addr_to_line.get(current_pc,'?')}")

            self.pc += 4
            return False

        elif opcode == 0b1100011:
            rs1 = extract_bits(instr,19,15)
            rs2 = extract_bits(instr,24,20)
            funct3 = extract_bits(instr,14,12)

            imm = sign_extend(
                (extract_bits(instr,31,31)<<12)|
                (extract_bits(instr,7,7)<<11)|
                (extract_bits(instr,30,25)<<5)|
                (extract_bits(instr,11,8)<<1),13)

            a,b = self.read_reg(rs1), self.read_reg(rs2)

            if funct3 == 0 and rs1==0 and rs2==0 and imm==0:
                return True

            cond = (
                (funct3==0 and a==b) or
                (funct3==1 and a!=b) or
                (funct3==4 and s32(a)<s32(b)) or
                (funct3==5 and s32(a)>=s32(b)) or
                (funct3==6 and u32(a)<u32(b)) or
                (funct3==7 and u32(a)>=u32(b))
            )

            self.pc = current_pc+imm if cond else current_pc+4
            return False

        elif opcode in (0b0110111,0b0010111):
            rd = extract_bits(instr,11,7)
            imm = extract_bits(instr,31,12)<<12
            self.write_reg(rd, imm if opcode==0b0110111 else current_pc+imm)
            self.pc += 4
            return False

        elif opcode == 0b1101111:
            rd = extract_bits(instr,11,7)
            imm = sign_extend(
                (extract_bits(instr,31,31)<<20)|
                (extract_bits(instr,19,12)<<12)|
                (extract_bits(instr,20,20)<<11)|
                (extract_bits(instr,30,21)<<1),21)
            self.write_reg(rd, current_pc+4)
            self.pc = current_pc+imm
            return False

        else:
            raise SimulationError(f"Error in line {self.addr_to_line.get(current_pc,'?')}")


def run_simulation_from_lines(lines):
    instructions=[]
    addr_to_line={}
    addr=0

    for i,line in enumerate(lines,1):
        line=line.strip()
        if not line: continue
        if len(line)!=32 or any(c not in "01" for c in line):
            raise SimulationError(f"Error in line {i}")
        instructions.append(int(line,2))
        addr_to_line[addr]=i
        addr+=4

    memory=Memory()
    memory.load_program(instructions)
    cpu=CPU(memory,addr_to_line)
    cpu.run()
    return cpu.trace_lines, memory.dump_data_memory_lines()


def main():
    try:
        if len(sys.argv)>=3:
            with open(sys.argv[1]) as f:
                lines=f.readlines()
            out=sys.argv[2]
        else:
            lines=sys.stdin.readlines()
            out=None

        trace,mem=run_simulation_from_lines(lines)
        text="\n".join(trace+mem)+"\n"

        if out:
            open(out,"w").write(text)
        else:
            print(text,end="")

    except SimulationError as e:
        msg=str(e)+"\n"
        if len(sys.argv)>=3:
            open(sys.argv[2],"w").write(msg)
        else:
            print(msg,end="")
