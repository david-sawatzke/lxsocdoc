from migen import *
from migen.util.misc import xdir
from migen.fhdl.specials import Memory

from litex.soc.interconnect.csr_bus import SRAM
from litex.soc.interconnect.csr import _CompoundCSR, CSRStatus, CSRStorage, CSRField, _CSRBase
from litex.soc.interconnect.csr_eventmanager import _EventSource, SharedIRQ, EventManager, EventSourceLevel, EventSourceProcess, EventSourcePulse

class DocumentedCSRField:
    def __init__(self, field):
        self.name        = field.name
        self.size        = field.size
        self.offset      = field.offset
        self.reset_value = field.reset
        self.description = field.description
        self.access      = field.access
        self.pulse       = field.pulse
        self.values      = field.values

        # If this is part of a sub-CSR, this value will be different
        self.start       = None

class DocumentedCSR:
    def trim(docstring):
        if docstring is not None:
            import textwrap
            return textwrap.dedent(docstring).replace("\n", " ")
        return None
        
    def __init__(self, name, address, short_name="", reset=0, offset=0, size=8, description=None, fields=[]):
        self.name = name
        self.short_name = short_name
        self.address = address
        self.offset = offset
        self.size = size
        if size == 0:
            print("!!! Warning: creating CSR of size 0 {}".format(name))
        self.description = DocumentedCSR.trim(description)
        self.reset = reset
        self.fields = fields
        for f in self.fields:
            f.description = DocumentedCSR.trim(f.description)

class DocumentedCSRRegion:
    def __init__(self, csr_region, module=None, submodules=[]):
        (self.name, self.origin, self.busword, self.raw_csrs) = csr_region
        self.current_address = self.origin
        self.sections = []
        self.csrs = []

        if hasattr(csr_region, "get_module_documentation"):
            print("Region {} has get_module_documentation()".format(self.name))
        for obj in submodules:
            if hasattr(obj, "get_module_documentation"):
                print("Submodule {} has get_module_documentation()".format(obj))
        if module is not None and hasattr(module, "get_module_documentation"):
            docs = module.get_module_documentation()
            for doc in docs:
                print("Module {} documentation: {}".format(self.name, doc))
                self.sections.append(doc)

        if isinstance(self.raw_csrs, SRAM):
            print("{}@{:x}: Found SRAM: {}".format(self.name, self.origin, self.raw_csrs))
        elif isinstance(self.raw_csrs, list):
            for csr in self.raw_csrs:
                if isinstance(csr, _CSRBase):
                    self.document_csr(csr)
                elif isinstance(csr, SRAM):
                    print("{}: Found SRAM in the list: {}".format(self.name, csr))
                else:
                    print("{}: Unknown module: {}".format(self.name, csr))
        elif isinstance(self.raw_csrs, Memory):
            print("{}@{:x}: Found memory that's {} x {} (but memories aren't documented yet)".format(self.name, self.origin, self.raw_csrs.width, self.raw_csrs.depth))
        else:
            print("{}@{:x}: Unexpected item on the CSR bus: {}".format(self.name, self.origin, self.raw_csrs))

    def bit_range(self, start, end, empty_if_zero=False):
        end -= 1
        if start == end:
            if empty_if_zero:
                return ""
            return "[{}]".format(start)
        else:
            return "[{}:{}]".format(end, start)

    def document_interrupt(self, soc, submodules, irq):
        managers = submodules["event_managers"]
        for m in managers:
            sources_u = [y for x, y in xdir(m, True) if isinstance(y, _EventSource)]
            sources = sorted(sources_u, key=lambda x: x.duid)

            def source_description(src):
                if hasattr(src, "name") and src.name is not None:
                    base_text = "`1` if a `{}` event occurred. ".format(src.name)
                else:
                    base_text = "`1` if a this particular event occurred. "
                if hasattr(src, "description") and src.description is not None:
                    return src.description
                elif isinstance(src, EventSourceLevel):
                    return base_text + "This Event is **level triggered** when the signal is **high**."
                elif isinstance(src, EventSourcePulse):
                    return base_text + "This Event is triggered on a **rising** edge."
                elif isinstance(src, EventSourceProcess):
                    return base_text + "This Event is triggered on a **falling** edge."
                else:
                    return base_text + "This Event uses an unknown method of triggering."

            # Patch the DocumentedCSR to add our own Description, if one doesn't exist.
            for dcsr in self.csrs:
                short_name = dcsr.short_name.upper()
                if short_name == m.status.name.upper():
                    if dcsr.fields is None or len(dcsr.fields) == 0:
                        fields = []
                        for i, source in enumerate(sources):
                            if hasattr(source, "name"):
                                fields.append(DocumentedCSRField(CSRField(source.name, offset=i, description="Level of the `{}` event".format(source.name))))
                            else:
                                fields.append(DocumentedCSRField(CSRField("event{}".format(i), offset=i, description="Level of the `event{}` event".format(i))))
                        dcsr.fields = fields
                    if dcsr.description is None:
                        dcsr.description = "This register contains the current raw level of the Event trigger.  Writes to this register have no effect."
                elif short_name == m.pending.name.upper():
                    if dcsr.fields is None or len(dcsr.fields) == 0:
                        fields = []
                        for i, source in enumerate(sources):
                            if hasattr(source, "name"):
                                fields.append(DocumentedCSRField(CSRField(source.name, offset=i, description=source_description(source))))
                            else:
                                fields.append(DocumentedCSRField(CSRField("event{}".format(i), offset=i, description=source_description(source))))
                        dcsr.fields = fields
                    if dcsr.description is None:
                        dcsr.description = "When an Event occurs, the corresponding bit will be set in this register.  To clear the Event, set the corresponding bit in this register."
                elif short_name == m.enable.name.upper():
                    if dcsr.fields is None or len(dcsr.fields) == 0:
                        fields = []
                        for i, source in enumerate(sources):
                            if hasattr(source, "name"):
                                fields.append(DocumentedCSRField(CSRField(source.name, offset=i, description="Write a `1` to enable the `{}` Event".format(source.name))))
                            else:
                                fields.append(DocumentedCSRField(CSRField("event{}".format(i), offset=i, description="Write a `1` to enable the `{}` Event".format(i))))
                        dcsr.fields = fields
                    if dcsr.description is None:
                        dcsr.description = "This register enables the corresponding Events.  Write a `0` to this register to disable individual events."

    def sub_csr_bit_range(self, csr, offset):
        nwords = (csr.size + self.busword - 1)//self.busword
        i = nwords - offset - 1
        nbits = min(csr.size - i*self.busword, self.busword) - 1
        name = (csr.name + str(i) if nwords > 1 else csr.name).upper()
        origin = i*self.busword
        return (origin, nbits, name)

    def split_fields(self, fields, start, end):
        """Split `fields` into a sub-list that only contains the fields
        between `start` and `end`.
        This means that sometimes registers will get truncated.  For example,
        if we're going from [8:15] and we have a register that spans [7:15],
        the bottom bit will be cut off.  To account for this, we set the `.start`
        property of the resulting split field to `1`, the `.offset` to `0`, and the
        `.size` to 7.
        """
        split_f = []
        for field in fields:
            if field.offset > end:
                continue
            if field.offset + field.size < start:
                continue
            new_field = DocumentedCSRField(field)

            new_field.offset -= start
            if new_field.offset < 0:
                underflow_amount = -new_field.offset
                new_field.offset = 0
                new_field.size  -= underflow_amount
                new_field.start  = underflow_amount
            # If it extends past the range, clamp the size to the range
            if new_field.offset + new_field.size > (end - start):
                new_field.size = (end - start) - new_field.offset + 1
                if new_field.start is None:
                    new_field.start = 0
            split_f.append(new_field)
        return split_f

    def print_reg(self, reg, stream):
        print("", file=stream)
        print("    .. wavedrom::", file=stream)
        print("        :caption: {}".format(reg.name), file=stream)
        print("", file=stream)
        print("        {", file=stream)
        print("            \"reg\": [", file=stream)
        if len(reg.fields) > 0:
            bit_offset = 0
            for field in reg.fields:
                field_name = field.name
                type_str = ""
                if field.pulse:
                    type_str = "\"type\": 4, "
                if hasattr(field, "start") and field.start is not None:
                    field_name = "{}{}".format(field.name, self.bit_range(field.start, field.size + field.start, empty_if_zero=True))
                term=","
                if bit_offset != field.offset:
                    print("                {\"bits\": " + str(field.offset - bit_offset) + "},", file=stream)
                if field.offset + field.size == self.busword:
                    term=""
                print("                {\"name\": \"" + field_name + "\",  " + type_str + "\"bits\": " + str(field.size) + "}" + term, file=stream)
                bit_offset = field.offset + field.size
            if bit_offset != self.busword:
                print("                {\"bits\": " + str(self.busword - bit_offset) + "}", file=stream)
        else:
            term=""
            if reg.size != 8:
                term=","
            print("                {\"name\": \"" + reg.short_name.lower() + self.bit_range(reg.offset, reg.offset + reg.size, empty_if_zero=True) + "\",  \"bits\": " + str(reg.size) + "}" + term, file=stream)
            if reg.size != 8:
                print("                {\"bits\": " + str(8 - reg.size) + "},", file=stream)
        print("            ], \"config\": {\"hspace\": 400, \"bits\": " + str(self.busword) + ", \"lanes\": 1 }, \"options\": {\"hspace\": 400, \"bits\": " + str(self.busword) + ", \"lanes\": 1}", file=stream)
        print("        }", file=stream)
        print("", file=stream)

    def get_csr_reset(self, csr):
        reset = 0
        if hasattr(csr, "fields"):
            for f in csr.fields.fields:
                reset = reset | (f.reset_value << f.offset)
        elif hasattr(csr, "storage"):
            reset = int(csr.storage.reset.value)
        elif hasattr(csr, "status"):
            reset = int(csr.status.reset.value)
        return reset

    def get_csr_size(self, csr):
        nbits = 0
        if hasattr(csr, "fields"):
            for f in csr.fields.fields:
                nbits = max(nbits, f.size + f.offset)
        elif hasattr(csr, "storage"):
            nbits = int(csr.storage.nbits)
        elif hasattr(csr, "status"):
            nbits = int(csr.status.nbits)
        elif hasattr(csr ,"r"):
            nbits = int(csr.r.nbits)
        elif hasattr(csr, "value"):
            nbits = int(csr.value.nbits)
        else:
            raise ValueError("Internal error: can't determine CSR size of {}".format(csr))
        return nbits

    def document_csr(self, csr):
        """Generates one or more DocumentedCSR, which will get appended
        to self.csrs"""
        fields = []
        description = None
        atomic_write = False
        full_name = self.name.upper() + "_" + csr.name.upper()
        reset = 0

        if hasattr(csr, "fields"):
            fields = csr.fields.fields
        if hasattr(csr, "description"):
            description = csr.description
        if hasattr(csr, "atomic_write"):
            atomic_write = csr.atomic_write
        size = self.get_csr_size(csr)
        reset = self.get_csr_reset(csr)

        # If the CSR is composed of multiple sub-CSRs, document each
        # one individually.
        if isinstance(csr, _CompoundCSR) and len(csr.simple_csrs) > 1:
            for i in range(len(csr.simple_csrs)):
                (start, length, name) = self.sub_csr_bit_range(csr, i)
                sub_name = self.name.upper() + "_" + name
                bits_str = "Bits {}-{} of `{}`.".format(start, start+length, full_name)
                if atomic_write:
                    if i == (range(len(csr.simple_csrs))-1):
                        bits_str += "Writing this register triggers an update of " + full_name
                    else:
                        bits_str += "The value won't take effect until `" + full_name + "0` is written."
                if i == 0:
                    d = description
                    if description is None:
                        d = bits_str
                    else:
                        d = bits_str + " " + d
                    self.csrs.append(DocumentedCSR(
                        sub_name, self.current_address, short_name=csr.name.upper(), reset=(reset>>start)&((2**length)-1),
                        offset=start,
                        description=d, fields=self.split_fields(fields, start, start + length)
                    ))
                else:
                    self.csrs.append(DocumentedCSR(
                        sub_name, self.current_address, short_name=csr.name.upper(), reset=(reset>>start)&((2**length)-1),
                        offset=start,
                        description=bits_str, fields=self.split_fields(fields, start, start + length)
                    ))
                self.current_address += 4
        else:
            self.csrs.append(DocumentedCSR(
                full_name, self.current_address, short_name=csr.name.upper(), reset=reset, size=size,
                description=description, fields=fields,
            ))
            self.current_address += 4

    def make_value_table(self, values):
        ret = ""
        max_value_width=len("Value")
        max_description_width=len("Description")
        for v in values:
            (value, name, description) = (None, None, None)
            if len(v) == 2:
                (value, description) = v
            elif len(v) == 3:
                (value, name, description) = v
            else:
                raise ValueError("Unexpected length of CSRField's value tuple")

            max_value_width = max(max_value_width, len(value))
            for d in description.splitlines():
                max_description_width = max(max_description_width, len(d))
        ret += "\n"
        ret += "+-" + "-"*max_value_width + "-+-" + "-"*max_description_width + "-+\n"
        ret += "| " + "Value".ljust(max_value_width) + " | " + "Description".ljust(max_description_width) + " |\n"
        ret += "+=" + "="*max_value_width + "=+=" +  "="*max_description_width + "=+\n"
        for v in values:
            (value, name, description) = (None, None, None)
            if len(v) == 2:
                (value, description) = v
            elif len(v) == 3:
                (value, name, description) = v
            else:
                raise ValueError("Unexpected length of CSRField's value tuple")
            value = value.ljust(max_value_width)
            first_line = True
            for d in description.splitlines():
                if first_line:
                    ret += "| {} | {} |\n".format(value, d.ljust(max_description_width))
                    first_line = False
                else:
                    ret += "| {} | {} |\n".format(" ".ljust(max_value_width), d.ljust(max_description_width))
            ret += "+-" + "-"*max_value_width + "-+-" + "-"*max_description_width + "-+\n"
        return ret

    def print_table(self, table, stream):
        column_widths = []

        print("", file=stream)
        if len(table) <= 0:
            return

        # Figure out how wide to make each column
        for col in table[0]:
            column_widths.append(0)

        for row in table:
            for i, column in enumerate(row):
                column_widths[i] = max(column_widths[i], len(column))

        # Print out header
        header = table.pop(0)
        print("+", file=stream, end="")
        for i, column in enumerate(header):
            print("-" + "-"*column_widths[i], file=stream, end="")
            print("-+", file=stream, end="")
        print("", file=stream)

        print("|", file=stream, end="")
        for i, column in enumerate(header):
            print(" " + column.ljust(column_widths[i]) + " |", file=stream, end="")
        print("", file=stream)

        print("+", file=stream, end="")
        for i, column in enumerate(header):
            print("=" + "="*column_widths[i], file=stream, end="")
            print("=+", file=stream, end="")
        print("", file=stream)

        for row in table:
            print("|", file=stream, end="")
            for i, column in enumerate(row):
                print(" " + column.ljust(column_widths[i]) + " |", file=stream, end="")
            print("", file=stream)

            print("+", file=stream, end="")
            for i, column in enumerate(row):
                print("-" + "-"*column_widths[i], file=stream, end="")
                print("-+", file=stream, end="")
            print("", file=stream)
        print("", file=stream)

    def print_region(self, stream):
        for section in self.sections:
            print("{}".format(section.title()), file=stream)
            print("-" * len(section.title()), file=stream)
            print(section.body(), file=stream)
            print("", file=stream)

        title = "Register Listing for {}".format(self.name.upper())
        print(title, file=stream)
        print("-" * len(title), file=stream)

        csr_table = [["Register", "Address"]]
        for csr in self.csrs:
            csr_table.append([csr.name, "``0x{:08x}``".format(csr.address)])
        self.print_table(csr_table, stream)

        for csr in self.csrs:
            print("{}".format(csr.name), file=stream)
            print("^" * len(csr.name), file=stream)
            print("", file=stream)
            print("**Address: 0x{:08x} + 0x{:x} = 0x{:08x}**".format(self.origin, csr.address - self.origin, csr.address), file=stream)
            print("", file=stream)
            if csr.description is not None:
                print("    {}".format(csr.description), file=stream)
            self.print_reg(csr, stream)
            if len(csr.fields) > 0:
                max_field_width=len("Field")
                max_name_width=len("Name")
                max_description_width=len("Description")
                value_tables = {}

                for f in csr.fields:
                    field = self.bit_range(f.offset, f.offset + f.size)
                    max_field_width = max(max_field_width, len(field))

                    name = f.name
                    if hasattr(f, "start") and f.start is not None:
                        name = "{}{}".format(f.name, self.bit_range(f.start, f.size + f.start))
                    max_name_width = max(max_name_width, len(name))

                    for d in f.description.splitlines():
                        max_description_width = max(max_description_width, len(d))
                    if f.values is not None:
                        value_tables[f.name] = self.make_value_table(f.values)
                        for d in value_tables[f.name].splitlines():
                            max_description_width = max(max_description_width, len(d))
                print("", file=stream)
                print("+-" + "-"*max_field_width + "-+-" + "-"*max_name_width + "-+-" + "-"*max_description_width + "-+", file=stream)
                print("| " + "Field".ljust(max_field_width) + " | " + "Name".ljust(max_name_width) + " | " + "Description".ljust(max_description_width) + " |", file=stream)
                print("+=" + "="*max_field_width + "=+=" + "="*max_name_width + "=+=" + "="*max_description_width + "=+", file=stream)
                for f in csr.fields:
                    field = self.bit_range(f.offset, f.offset + f.size).ljust(max_field_width)

                    name = f.name.upper()
                    if hasattr(f, "start") and f.start is not None:
                        name = "{}{}".format(f.name.upper(), self.bit_range(f.start, f.size + f.start))
                    name = name.ljust(max_name_width)

                    description = f.description
                    if f.name in value_tables:
                        description += "\n" + value_tables[f.name]

                    first_line = True
                    for d in description.splitlines():
                        if first_line:
                            print("| {} | {} | {} |".format(field, name, d.ljust(max_description_width)), file=stream)
                            first_line = False
                        else:
                            print("| {} | {} | {} |".format(" ".ljust(max_field_width), " ".ljust(max_name_width), d.ljust(max_description_width)), file=stream)
                    print("+-" + "-"*max_field_width + "-+-" + "-"*max_name_width + "-+-" + "-"*max_description_width + "-+", file=stream)
            print("", file=stream)