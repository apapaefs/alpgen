import string
import numpy
import math
import threading
from threading import Thread
import logging
from tqdm import tqdm
import subprocess

#########################
# FUNCTIONS             #
#########################

# function to get template
def getTemplate(basename):
    with open('%s.template' % basename, 'r') as f:
        templateText = f.read()
    return string.Template( templateText )

# write a filename
def writeFile(filename, text):
    with open(filename,'w') as f:
        f.write(text)


def Run_AlpGen(InputFile, AlpGen_exec='4Qgen'):
    AlpGen_Command = './' + AlpGen_exec + ' < ' + InputFile
    print('Executing', AlpGen_Command)
    p = subprocess.Popen(AlpGen_Command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd='.')
    #for line in iter(p.stdout.readline, b''):
    #    print('\t\t', line, end=' ')
    out, err = p.communicate()
    #time.sleep(10)
    #logging.info("Thread %s: finishing", file_number)


############################
# RUN                      #
############################

###############
# weighted run:
###############

# generate files from templates
TemplateName = 'input_4b2j_13.6_LHAPDF'
TemplateGen = getTemplate(TemplateName)

# options:
NRuns = 100 # the number of runs
PDFName = 'NNPDF23_nlo_as_0119'
NEVENTS = 1000000000
NEVENTSGRID = 10000000

# lists to hold seeds
SEEDs1 = []
SEEDs2 = []
SEEDs3 = []
SEEDs4 = []

# list with input files generated
InputFiles = []

# generate seeds
for i in range(NRuns):
    SEEDs1.append(str(10000 + i))
    SEEDs2.append(str(20000 + i))
    SEEDs3.append(str(30000 + i))
    SEEDs4.append(str(40000 + i))

for j in range(NRuns):
    TAG = TemplateName.replace('input_','') +  '_' + PDFName + '_' + str(j)
    parmtextsubs = {
            'PDF' : PDFName,
            'SEED1' : SEEDs1[j],
            'SEED2' : SEEDs2[j],
            'SEED3' : SEEDs3[j],
            'SEED4' : SEEDs4[j],
            'TAG': TAG,
            'NEVENTSGRID': NEVENTSGRID,
            'NEVENTS': NEVENTS

        }
    OutputFile = TemplateName + '_' + PDFName + '_' + str(j)
    InputFiles.append(OutputFile) # append input files to list
    print('\t\twriting', './' + OutputFile)
    writeFile('./' + OutputFile , TemplateGen.substitute(parmtextsubs) )


# launch the threads
format = "%(asctime)s: %(message)s"
logging.basicConfig(format=format, level=logging.INFO,datefmt="%H:%M:%S")
threads = list()
logging.info("Main    : starting threads")
for j in tqdm(range(len(InputFiles))):
        x = threading.Thread(target=Run_AlpGen, args=(InputFiles[j],))
        threads.append(x)
        x.start()

logging.info("Done with all AlpGen weighted runs!")
