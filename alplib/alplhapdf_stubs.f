C----------------------------------------------------------------------
C     LHAPDF6 stub routines for ALPGEN
C
C     These stubs are linked when building WITHOUT LHAPDF6 support.
C     They provide the symbols that alpgen.f and alppdf.f reference,
C     but stop with an error if actually called (ilhapdf=1 without
C     linking the real LHAPDF library).
C
C     When building WITH LHAPDF6 (make gen-lhapdf LHAPDF=yes),
C     the real alplhapdf.o is linked instead, which provides the
C     actual implementations.
C----------------------------------------------------------------------

C----------------------------------------------------------------------
      SUBROUTINE LHAPDF_INIT(SETNAME,IMEM)
C----------------------------------------------------------------------
      IMPLICIT NONE
      CHARACTER*128 SETNAME
      INTEGER IMEM
C
      WRITE(6,*) 'ERROR: LHAPDF6 support not compiled in.'
      WRITE(6,*) 'Rebuild with: make gen-lhapdf LHAPDF=yes'
      STOP
      END

C----------------------------------------------------------------------
      SUBROUTINE MLMPDF_LHAPDF(IH,Q2,X,FX,NF)
C----------------------------------------------------------------------
      IMPLICIT NONE
      INTEGER IH,NF
      REAL FX(-NF:NF)
      REAL Q2,X
C
      WRITE(6,*) 'ERROR: LHAPDF6 support not compiled in.'
      WRITE(6,*) 'Rebuild with: make gen-lhapdf LHAPDF=yes'
      STOP
      END

C----------------------------------------------------------------------
      SUBROUTINE LHAPDF_GETLAM(XLAM,NLOOP,SCHE)
C----------------------------------------------------------------------
      IMPLICIT NONE
      DOUBLE PRECISION XLAM
      INTEGER NLOOP
      CHARACTER*2 SCHE
C
      WRITE(6,*) 'ERROR: LHAPDF6 support not compiled in.'
      WRITE(6,*) 'Rebuild with: make gen-lhapdf LHAPDF=yes'
      STOP
      END
