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

# 6Qg process

This repository includes a `6Qg` process library for generating `6b+g`
events.  It is based on the ALPGEN `4Q` code path, uses the `jproc=6`
matrix element with `njets=3`, and hard-wires the heavy flavours to bottom,
so the hard process is `gg -> b bbar b bbar b bbar g`.

The top-level `Makefile` includes `6Qg` in `PROCLIST`.  Example inputs for
LHAPDF tests with `NNPDF23_nlo_as_0119` are in `6Qgwork/input_6b1g_lhapdf_*`.

# Herwig forced-splitting workflow

The approximate `8b` workflow starts from the ALPGEN `6b+g` LHE file and uses
Herwig to keep only one final-state `g -> b bbar` shower emission.  The
example steering file is `6Qgwork/AlpGen8Q-LHEWriter.in`.

The shower forcing/veto logic lives outside this AlpGen repository in the
private plugin repository
[`herwig-min-b-shower-veto`](https://github.com/apapaefs/herwig-min-b-shower-veto).
That plugin provides `Herwig::MinBShowerVeto`, which can require at least
eight final-state `b/bbar` quarks and write a sidecar acceptance estimate via
`ProbeTrials`/`CorrectionFile`.  When rate-corrected forced samples are needed,
the forced LHE event weights should be multiplied by the sidecar `p_hat`.
This is a conditional shower approximation, not a replacement for a full
`gg -> 8b` matrix element.

# AI/LLM Usage

A large part of these modifications have been generated via Claude Code and Codex.
