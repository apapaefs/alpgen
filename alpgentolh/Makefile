# Makefile for AlpGenToLH
# Converts AlpGen .unw files to Les Houches Event (LHE) format
#
# Usage:
#   make            - build AlpGenToLH
#   make clean      - remove compiled files
#
# The resulting executable reads AlpGen unweighted event files
# and produces .lhe files suitable for input to event generators
# such as Herwig 7.

CXX ?= g++
CXXFLAGS ?= -O2

AlpGenToLH: AlpGenToLH.cc
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	-rm -f AlpGenToLH

.PHONY: clean
