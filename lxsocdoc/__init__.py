#!/usr/bin/env python3

# Disable pylint's E1101, which breaks completely on migen
#pylint:disable=E1101

from litex.soc.interconnect.csr import _CompoundCSR
from .csr import DocumentedCSR, DocumentedCSRField, DocumentedCSRRegion
from .module import ModuleDocumentation, AutoDocument, gather_submodules

sphinx_configuration = """
project = '{}'
copyright = '{}, {}'
author = '{}'
extensions = [
    'sphinxcontrib.wavedrom',
    {}
]
templates_path = ['_templates']
exclude_patterns = []
offline_skin_js_path = "https://wavedrom.com/skins/default.js"
offline_wavedrom_js_path = "https://wavedrom.com/WaveDrom.js"
html_theme = 'alabaster'
html_static_path = ['_static']
"""

def sub_csr_bit_range(busword, csr, offset):
    nwords = (csr.size + busword - 1)//busword
    i = nwords - offset - 1
    nbits = min(csr.size - i*busword, busword) - 1
    name = (csr.name + str(i) if nwords > 1 else csr.name).upper()
    origin = i*busword
    return (origin, nbits, name)

def print_svd_register(csr, csr_address, description, svd):
    print('                <register>', file=svd)
    print('                    <name>{}</name>'.format(csr.name), file=svd)
    if description is not None:
        print('                    <description>{}</description>'.format(description), file=svd)
    print('                    <addressOffset>0x{:04x}</addressOffset>'.format(csr_address), file=svd)
    print('                    <resetValue>0x{:02x}</resetValue>'.format(csr.reset), file=svd)
    csr_address = csr_address + 4
    if hasattr(csr, "fields"):
        print('                    <fields>', file=svd)
        for field in csr.fields:
            print('                        <field>', file=svd)
            print('                            <name>{}</name>'.format(field.name), file=svd)
            print('                            <msb>{}</msb>'.format(field.offset + field.size - 1), file=svd)
            print('                            <bitRange>[{}:{}]</bitRange>'.format(field.offset + field.size - 1, field.offset), file=svd)
            print('                            <lsb>{}</lsb>'.format(field.offset), file=svd)
            print('                            <description>{}</description>'.format(field.description), file=svd)
            print('                        </field>', file=svd)
        print('                    </fields>', file=svd)
    print('                </register>', file=svd)

def generate_svd(soc, buildpath, vendor="litex", name="soc"):
    interrupts = {}
    for csr, irq in sorted(soc.soc_interrupt_map.items()):
        interrupts[csr] = irq

    documented_regions = []
    regions = soc.get_csr_regions()
    for csr_region in regions:
        documented_regions.append(DocumentedCSRRegion(csr_region))

    with open(buildpath + "/" + name + ".svd", "w", encoding="utf-8") as svd:
        print('<?xml version="1.0" encoding="utf-8"?>', file=svd)
        print('', file=svd)
        print('<device schemaVersion="1.1" xmlns:xs="http://www.w3.org/2001/XMLSchema-instance" xs:noNamespaceSchemaLocation="CMSIS-SVD.xsd" >', file=svd)
        print('    <vendor>{}</vendor>'.format(vendor), file=svd)
        print('    <name>{}</name>'.format(name.upper()), file=svd)
        print('', file=svd)
        print('    <addressUnitBits>8</addressUnitBits>', file=svd)
        print('    <width>32</width>', file=svd)
        print('    <size>32</size>', file=svd)
        print('    <access>read-write</access>', file=svd)
        print('    <resetValue>0x00000000</resetValue>', file=svd)
        print('    <resetMask>0xFFFFFFFF</resetMask>', file=svd)
        print('', file=svd)
        print('    <peripherals>', file=svd)

        for region in documented_regions:
            csr_address = 0
            print('        <peripheral>', file=svd)
            print('            <name>{}</name>'.format(region.name.upper()), file=svd)
            print('            <baseAddress>0x{:08X}</baseAddress>'.format(region.origin), file=svd)
            print('            <groupName>{}</groupName>'.format(region.name.upper()), file=svd)
            print('            <description></description>', file=svd)
            print('            <registers>', file=svd)
            for csr in region.csrs:
                description = None
                if hasattr(csr, "description"):
                    description = csr.description
                if isinstance(csr, _CompoundCSR) and len(csr.simple_csrs) > 1:
                    is_first = True
                    for i in range(len(csr.simple_csrs)):
                        (start, length, name) = sub_csr_bit_range(region_busword, csr, i)
                        sub_name = csr.name.upper() + "_" + name
                        bits_str = "Bits {}-{} of `{}`.".format(start, start+length, csr.name)
                        if is_first:
                            if description is not None:
                                print_svd_register(csr.simple_csrs[i], csr_address, bits_str + " " + description, svd)
                            else:
                                print_svd_register(csr.simple_csrs[i], csr_address, bits_str, svd)
                            is_first = False
                        else:
                            print_svd_register(csr.simple_csrs[i], csr_address, bits_str, svd)
                        csr_address = csr_address + 4
                else:
                    print_svd_register(csr, csr_address, description, svd)
                    csr_address = csr_address + 4
            print('            </registers>', file=svd)
            print('            <addressBlock>', file=svd)
            print('                <offset>0</offset>', file=svd)
            print('                <size>0x{:x}</size>'.format(csr_address), file=svd)
            print('                <usage>registers</usage>', file=svd)
            print('            </addressBlock>', file=svd)
            if region.name in interrupts:
                print('            <interrupt>', file=svd)
                print('                <name>{}</name>'.format(region.name), file=svd)
                print('                <value>{}</value>'.format(interrupts[region.name]), file=svd)
                print('            </interrupt>', file=svd)
            print('        </peripheral>', file=svd)
        print('    </peripherals>', file=svd)
        print('</device>', file=svd)

def generate_docs(soc, base_dir, project_name="LiteX SoC Project", author="Anonymous", sphinx_extensions=[], quiet=False):
    """Possible extra extensions:
        [
            'recommonmark',
            'sphinx_rtd_theme',
            'sphinx_autodoc_typehints',
        ]
    """

    # Connect interrupts
    if not hasattr(soc, "cpu"):
        raise ValueError("Module has no CPU attribute")
    if not hasattr(soc.cpu, "interrupt"):
        raise ValueError("CPU has no interrupt module")

    # Ensure the target directory is a full path
    if base_dir[-1] != '/':
        base_dir = base_dir + '/'

    # Ensure the output directory exists
    import pathlib
    pathlib.Path(base_dir + "/_static").mkdir(parents=True, exist_ok=True)

    # Create various Sphinx plumbing
    with open(base_dir + "conf.py", "w", encoding="utf-8") as conf:
        import datetime
        year = datetime.datetime.now().year
        print(sphinx_configuration.format(project_name, year, author, author, ",\n    ".join(sphinx_extensions)), file=conf)
    if not quiet:
        print("Generate the documentation by running `sphinx-build -M html {} {}_build`".format(base_dir, base_dir))

    # Gather all interrupts so we can easily map IRQ numbers to CSR sections
    interrupts = {}
    for csr, irq in sorted(soc.soc_interrupt_map.items()):
        interrupts[csr] = irq

    # Convert each CSR region into a DocumentedCSRRegion.
    # This process will also expand each CSR into a DocumentedCSR,
    # which means that CompoundCSRs (such as CSRStorage and CSRStatus)
    # that are larger than the buswidth will be turned into multiple
    # DocumentedCSRs.
    documented_regions = []
    regions = soc.get_csr_regions()
    for csr_region in regions:
        if not hasattr(soc, csr_region[0]):
            raise ValueError("SOC has no module {}".format(csr_region[0]))
        module = getattr(soc, csr_region[0])
        submodules = gather_submodules(module)

        documented_region = DocumentedCSRRegion(csr_region, module, submodules)
        if documented_region.name in interrupts:
            documented_region.document_interrupt(soc, submodules, interrupts[documented_region.name])
        documented_regions.append(documented_region)

    with open(base_dir + "index.rst", "w", encoding="utf-8") as index:
        print("""
Documentation for {}
{}

.. toctree::
    :hidden:
""".format(project_name, "="*len("Documentation for " + project_name)), file=index)
        for region in documented_regions:
            print("    {}".format(region.name), file=index)

        print("""
Register Groups
===============
""", file=index)
        for region in documented_regions:
            print("* :doc:`{} <{}>`".format(region.name.upper(), region.name), file=index)

        print("""
Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
""", file=index)

    # Create a Region file for each of the documented CSR regions.
    for region in documented_regions:
        with open(base_dir + region.name + ".rst", "w", encoding="utf-8") as outfile:
            region.print_region(outfile)