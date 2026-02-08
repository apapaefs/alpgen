# DEFINE FORTRAN COMPILATION DEFAULTS

ifeq ($(shell uname),AIX)
 FFF = xlf -O4
 FF90 = xlf90 -O4 -qsuffix=f=f90:o=o90
endif

ifeq ($(shell uname),Linux)
  FFF = gfortran-10 -fno-automatic  -O2 -fallow-argument-mismatch
  FF90 = gfortran-10 -fno-automatic -O2 -fallow-argument-mismatch
#FFF = g77 -O1 -Wall -fno-automatic -Wno-globals -fno-backslash \
#	 -ffast-math
endif

ifeq ($(shell uname),Darwin)
  ifeq  ($(shell uname -m),Power Macintosh) 
     FFF = g77 -O1 -Wall -fno-automatic -Wno-globals -fno-backslash \
	 -ffast-math
  endif
  ifeq  ($(shell uname -m),i386) 
     FFF = ifort -V -noautomatic -warn
     FF90 = ifort -V -noautomatic -warn
     FFF = gfortran -fno-automatic
	FF90 = gfortran -fno-automatic
  endif
  ifeq ($(shell uname -m),arm64)
      FFF = gfortran-15 -fno-automatic  -O2 -fallow-argument-mismatch
      FF90 = gfortran-15 -fno-automatic -O2 -fallow-argument-mismatch
  endif
endif
# Unix-ALPHA fortran
# FFF = f90 -fast
# FF90 = f90 -fast

# LHAPDF6 support
# Set LHAPDF=yes to enable linking with LHAPDF6
# Requires lhapdf-config to be in PATH, or set LHAPDF_CONFIG manually
# Usage: make gen LHAPDF=yes
LHAPDF_CONFIG ?= lhapdf-config
ifeq ($(LHAPDF),yes)
  LHAPDF_INC = $(shell $(LHAPDF_CONFIG) --cflags 2>/dev/null)
  LHAPDF_LIB = $(shell $(LHAPDF_CONFIG) --libs 2>/dev/null)
  ifeq ($(LHAPDF_LIB),)
    $(warning LHAPDF=yes but lhapdf-config not found. Set LHAPDF_CONFIG or ensure LHAPDF6 is installed.)
  endif
else
  LHAPDF_INC =
  LHAPDF_LIB =
endif

