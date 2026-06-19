# AlpGenMod: AlpGen with LHAPDF 6

This repository modifies the original [ALPGEN](https://alpgen.web.cern.ch)
event generator, version 2.14, to work on modern systems.

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

# 6Qg campaign driver

Parallel `6b+g -> 8b` campaigns can be run from `6Qgwork` with:

```
python3 run_6qg_8b_campaign.py --target-events 100000 --jobs 32 \
  --setup-command 'module load herwig/stable-full-py3-rivet4'
```

The default template is `input_6b1g_lhapdf_example2`, which uses one 1M-event
warmup iteration followed by 100M weighted-generation trials.
All generated files are written under `6Qgwork/campaigns/<campaign>/`.  Each
run has a unique tag, per-run inputs/logs/manifests, and a final reweighted
LHE.  The driver prints live per-run stage updates plus periodic ETA summaries.
During AlpGen mode 1 it also polls each run's `<tag>.mon`/`<tag>.stat` files to
report warmup/weighted-generation event progress and per-run ETA.  Use
`--progress-interval` for summary cadence, `--alpgen-progress-interval` for
AlpGen file polling cadence, or `--no-progress` to disable the live monitor.
Use `--dry-run` to inspect the planned run directories and commands without
launching AlpGen or Herwig.

# AI/LLM Usage

A large part of these modifications have been generated via Claude Code and Codex.
