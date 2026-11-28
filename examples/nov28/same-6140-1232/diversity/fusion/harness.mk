# Invoke from a configured, compiled Dream console build directory.
include Makefile
fusion_source := $(dir $(abspath $(filter %harness.mk,$(MAKEFILE_LIST))))decoder.cpp
.PHONY: fusion-decoder
fusion-decoder:
	$(CXX) $(CXXFLAGS) $(INCPATH) -I"$(DREAM_SOURCE)" -std=c++17 -c "$(fusion_source)" -o "$(OUTDIR)/decoder.o"
	$(LINK) $(LFLAGS) -o "$(OUTDIR)/decoder" "$(OUTDIR)/decoder.o" $(filter-out main.o %/main.o,$(OBJECTS)) $(LIBS)
