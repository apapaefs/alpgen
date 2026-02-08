C----------------------------------------------------------------------
C     LHAPDF6 interface for ALPGEN
C
C     This file provides the interface routines to use LHAPDF6
C     (C++ library) from within ALPGEN.
C
C     LHAPDF6 provides backward-compatible Fortran wrappers (LHAGLUE)
C     that match the LHAPDF5 calling convention:
C       call InitPDFsetByName(setname)
C       call InitPDF(imem)
C       call evolvePDF(x, Q, f)      ! f(-6:6) = x*f(x,Q)
C       alphasPDF = alphaspdf(Q)     ! double precision function
C       call GetOrderAs(order)       ! integer order
C
C     Flavor convention:
C       LHAPDF (PDG):  -5..5 where 1=d, 2=u, 3=s, 4=c, 5=b, 0=g
C       ALPGEN:        -5..5 where 1=u, 2=d, 3=s, 4=c, 5=b, 0=g
C       So we swap 1<->2 (and -1<->-2) when converting from LHAPDF.
C
C----------------------------------------------------------------------

C----------------------------------------------------------------------
      SUBROUTINE LHAPDF_INIT(SETNAME,IMEM)
C----------------------------------------------------------------------
C     Initialise LHAPDF6 with a given PDF set and member number
C----------------------------------------------------------------------
      IMPLICIT NONE
      CHARACTER*128 SETNAME
      INTEGER IMEM
C
      WRITE(6,*) '================================================='
      WRITE(6,*) 'Initialising LHAPDF6'
      WRITE(6,*) '  PDF set:    ',TRIM(SETNAME)
      WRITE(6,*) '  Member:     ',IMEM
      WRITE(6,*) '================================================='
C
C     Initialise the PDF set using LHAGLUE wrapper
      CALL InitPDFsetByName(TRIM(SETNAME))
C
C     Select the member
      CALL InitPDF(IMEM)
C
      WRITE(6,*) 'LHAPDF6 initialisation complete.'
      WRITE(6,*) '================================================='
C
      RETURN
      END

C----------------------------------------------------------------------
      SUBROUTINE MLMPDF_LHAPDF(IH,Q2,X,FX,NF)
C----------------------------------------------------------------------
C     Evaluate PDFs using LHAPDF6
C     Returns PDFs in ALPGEN convention: 1=u, 2=d (not PDG)
C
C     IH:  hadron type (1=proton, 2=neutron, 0=isospin average)
C     Q2:  factorisation scale squared (GeV^2)
C     X:   Bjorken x
C     FX:  output PDF array FX(-NF:NF)
C     NF:  number of active flavours (typically 5)
C----------------------------------------------------------------------
      IMPLICIT NONE
      INTEGER IH,NF
      REAL FX(-NF:NF)
      REAL Q2,X
      DOUBLE PRECISION DX,DQ
      DOUBLE PRECISION XFPDG(-6:6)
      REAL TMP
      INTEGER I
C
C     Convert to double precision
      DX = DBLE(X)
      DQ = DBLE(SQRT(Q2))
C
C     Call LHAPDF6 (LHAGLUE) to get all flavors in PDG convention
C     evolvePDF returns x*f(x,Q) for all flavours -6..6
      CALL evolvePDF(DX, DQ, XFPDG)
C
C     Fill ALPGEN FX array
C     LHAPDF (PDG): 0=g, 1=d, 2=u, 3=s, 4=c, 5=b
C     ALPGEN:       0=g, 1=u, 2=d, 3=s, 4=c, 5=b
C     Convert from x*f(x) to f(x) by dividing by x
      IF(DX.GT.0D0) THEN
C       Gluon
        FX(0) = SNGL(XFPDG(0) / DX)
C       u quark (PDG index 2) -> ALPGEN index 1
        FX(1)  = SNGL(XFPDG(2) / DX)
        FX(-1) = SNGL(XFPDG(-2) / DX)
C       d quark (PDG index 1) -> ALPGEN index 2
        FX(2)  = SNGL(XFPDG(1) / DX)
        FX(-2) = SNGL(XFPDG(-1) / DX)
C       s, c, b quarks (same index in both conventions)
        DO I = 3, NF
          FX(I)  = SNGL(XFPDG(I) / DX)
          FX(-I) = SNGL(XFPDG(-I) / DX)
        ENDDO
      ELSE
        DO I = -NF, NF
          FX(I) = 0.0
        ENDDO
      ENDIF
C
C     Handle neutron: swap u <-> d (indices 1 <-> 2 in ALPGEN convention)
      IF(ABS(IH).EQ.2) THEN
        TMP    = FX(1)
        FX(1)  = FX(2)
        FX(2)  = TMP
        TMP    = FX(-1)
        FX(-1) = FX(-2)
        FX(-2) = TMP
      ENDIF
C
C     Handle isospin average
      IF(IH.EQ.0) THEN
        FX(1)  = 0.5 * ( FX(1)+FX(2) )
        FX(-1) = 0.5 * ( FX(-1)+FX(-2) )
        FX(2)  = FX(1)
        FX(-2) = FX(-1)
      ENDIF
C
      RETURN
      END

C----------------------------------------------------------------------
      SUBROUTINE LHAPDF_GETLAM(XLAM,NLOOP,SCHE)
C----------------------------------------------------------------------
C     Get QCD parameters from LHAPDF6 for use in ALPGEN's alpha_s
C
C     XLAM:  Lambda_QCD (5-flavour) [output]
C     NLOOP: loop order for alpha_s [output]
C     SCHE:  scheme (MS or DI) [output]
C
C     Since LHAPDF6 does not directly provide Lambda_QCD, we
C     extract alpha_s(MZ) and the QCD order, then compute Lambda
C     by inverting ALPGEN's own alfas() function via bisection.
C----------------------------------------------------------------------
      IMPLICIT NONE
      DOUBLE PRECISION XLAM
      INTEGER NLOOP
      CHARACTER*2 SCHE
      DOUBLE PRECISION ALPHAS_MZ,DMZ
      DOUBLE PRECISION ALFAS
      EXTERNAL ALFAS
      DOUBLE PRECISION ALPHASPDF
      EXTERNAL ALPHASPDF
      INTEGER ORDERQCD
C
C     MZ value
      DMZ = 91.1876D0
C
C     Get alpha_s(MZ) from LHAPDF
      ALPHAS_MZ = ALPHASPDF(DMZ)
C
C     Get QCD perturbative order from LHAPDF (0=LO, 1=NLO, 2=NNLO)
      CALL GetOrderAs(ORDERQCD)
C
C     Set loop order: LHAPDF order 0=LO->nloop=1, 1=NLO->nloop=2
      NLOOP = ORDERQCD + 1
      IF(NLOOP.LT.1) NLOOP = 1
      IF(NLOOP.GT.2) NLOOP = 2
C
C     Scheme is always MSbar for modern PDF sets
      SCHE = 'MS'
C
C     Compute Lambda_5 from alpha_s(MZ) by inverting the alpha_s formula
C     using ALPGEN's own alfas() routine via bisection
      CALL LHAPDF_FINDLAM(ALPHAS_MZ,DMZ,NLOOP,XLAM)
C
      WRITE(6,*) 'LHAPDF6 QCD parameters:'
      WRITE(6,*) '  alpha_s(MZ) = ',ALPHAS_MZ
      WRITE(6,*) '  QCD order   = ',ORDERQCD,' (nloop=',NLOOP,')'
      WRITE(6,*) '  Lambda_5    = ',XLAM
      WRITE(6,*) '  Scheme      = ',SCHE
C
      RETURN
      END

C----------------------------------------------------------------------
      SUBROUTINE LHAPDF_FINDLAM(ASMZ,DMZ,NLOOP,XLAM)
C----------------------------------------------------------------------
C     Find Lambda_QCD that reproduces the given alpha_s(MZ)
C     using ALPGEN's own alfas() routine, by bisection.
C
C     alpha_s increases with Lambda_QCD at fixed Q, so:
C       alfas(MZ,lam) > target => lam too big
C----------------------------------------------------------------------
      IMPLICIT NONE
      DOUBLE PRECISION ASMZ,DMZ,XLAM
      INTEGER NLOOP
      DOUBLE PRECISION ALFAS
      EXTERNAL ALFAS
      DOUBLE PRECISION LAMLO,LAMHI,LAMMID,ASMID
      DOUBLE PRECISION MZ2
      INTEGER ITER
C
      MZ2 = DMZ**2
      LAMLO  = 0.050D0
      LAMHI  = 0.500D0
C
      DO ITER = 1, 100
        LAMMID = 0.5D0*(LAMLO+LAMHI)
        ASMID = ALFAS(MZ2,LAMMID,NLOOP,-1)
        IF(ASMID .GT. ASMZ) THEN
          LAMHI = LAMMID
        ELSE
          LAMLO = LAMMID
        ENDIF
        IF(ABS(LAMHI-LAMLO).LT.1D-6) GOTO 10
      ENDDO
 10   XLAM = 0.5D0*(LAMLO+LAMHI)
C
      RETURN
      END
