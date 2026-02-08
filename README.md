# AlpGenMod: AlpGen with LHAPDF 6

This is a modification of AlpGen version 2.14 to work on modern systems

# Compilation

## Standard build (unchanged, no LHAPDF): 

For a standard build (no LHAPDF), e.g. in a directory ```4Qwork```: 

```
make gen
```

Then link the pdfs with ```./pdflink```

## Build with LHAPDF6

To build with LHAPDF 6 (if already in path): 

```
make gen-plhapdf LHAPDF=yes
```

If LHAPDF is not in your PATH:
```
make gen-lhapdf LHAPDF=yes LHAPDF_CONFIG=/path/to/lhapdf-config
```

# Usage

The standard input files should work with the following modifications for LHAPDF:

To enable LHAPDF: 

```
ilhapdf 1
```

And to choose the PDF name and member:

```
lhapdfst PDF_NAME
lhapdfid 0
```

where ```lhapdfst``` is the set name and ```lhapdfid``` is the id. 

# AI/LLM Usage

A large part of these modifications have been generated via ChatGPT and Claude Code. 
