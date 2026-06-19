import sys
import pylab as pl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import colors
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import math
from tqdm import tqdm
import matplotlib.gridspec as gridspec # more plotting
import gzip
import matplotlib.ticker as ticker
from matplotlib.ticker import MultipleLocator

###########################################################
# Handle the input here.
# The default output file tag (i.e. extension) is 'output'.
###########################################################

if len(sys.argv) < 2:
    print('lhe_analyzer.py [lhe file] ([output file tag])')
    exit()

inputfile = str(sys.argv[1])

outputfiletag = ''

if len(sys.argv) > 2:
    inputfile2 = str(sys.argv[2])

if len(sys.argv) > 3:
    inputfile3 = str(sys.argv[3])



##########################
# FUNCTIONS
##########################

# Functions to handle colors in matplotlib plots:
# choose the next colour -- for plotting
ccount = 0
def next_color():
    global ccount
    colors = [ 'red', 'blue', 'green', 'orange','black', 'cyan', 'magenta', 'brown', 'violet'] # 9 colours
    color_chosen = colors[ccount]
    if ccount < 8:
        ccount = ccount + 1
    else:
        ccount = 0
    return color_chosen
# do not increment colour in this case:
def same_color():
    global ccount
    colors = [ 'red', 'blue', 'black', 'green', 'orange','cyan', 'magenta', 'brown', 'violet'] # 9 colours
    color_chosen = colors[ccount-1]
    return color_chosen
# reset the color counter:
def reset_color():
    global ccount
    ccount = 0


# function to plot histograms: including the cross section normalization and STACKED
# DATA_array contains ARRAYS of data for each event. Each array represents a different type of input (e.g. a run with different parameters, etc.).
# CrossSection_array contains ARRAYS of cross sections
# plot_type is simply the main name of the plot
# plotnames_multi has to be an array of equal size to DATA_array
# custom_bins can be provided for the desired observable
def histogram_multi_xsec_stacked(DATA_array, CrossSection_array, plot_type, plotnames_multi, xlabel='', ylabel='fraction/bin', nbins=50, title='', custom_bins=[], ylogbool=False, xlogbool=False):
    print('---')
    print('plotting', plot_type)

    # plot settings ########
    ylab = ylabel # the ylabel
    xlab = xlabel # the x label
    # log scale?
    ylog = ylogbool # whether to plot y in log scale
    xlog = xlogbool # whether to plot x in log scale

    # construct the axes for the plot
    # no need to modify this if you just need one plot
    gs = gridspec.GridSpec(4, 4)
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.grid(False)

    # loop over the DATA in the DATA_array
    # get the errors per bin and normalize so that we obtain fraction of events/bin
    dd = 0
    X = []
    Y = []
    binstot = []
    for DATA in DATA_array:
        if len(custom_bins) == 0:
            bins, edges = np.histogram(np.array(DATA), bins=nbins)
        else:
            bins, edges = np.histogram(np.array(DATA), bins=custom_bins)
        errors = np.divide(np.sqrt(bins), bins, out=np.zeros_like(np.sqrt(bins)), where=bins!=0.)
        bins = bins/float(len(DATA))
        errors = bins*errors
        #print(bins)
        #print(errors)
        left,right = edges[:-1],edges[1:]
        X = np.array([left,right]).T.flatten()
        if len(Y) == 0:
            Y = np.array([bins,bins]).T.flatten()*CrossSection_array[dd]
            binstot = bins/float(len(DATA))*CrossSection_array[dd]
        else:
            Y = Y + np.array([bins,bins]).T.flatten()*CrossSection_array[dd]
            binstot = binstot + bins/float(len(DATA))*CrossSection_array[dd]
        dd = dd+1
    center = (edges[:-1] + edges[1:]) / 2
    plt.plot(X,Y, label='total', color=next_color(), lw=1)
    #plt.errorbar(X, Y, yerr=., color=same_color(), lw=0, elinewidth=1, capsize=1)


    # set the ticks, labels and limits etc.
    ax.set_ylabel(ylab, fontsize=20)
    ax.set_xlabel(xlab, fontsize=20)

    # choose x and y log scales
    if ylog:
        ax.set_yscale('log')
    else:
        ax.set_yscale('linear')
    if xlog:
        ax.set_xscale('log')
    else:
        ax.set_xscale('linear')

    # set the limits on the x and y axes if required below:
    # (this is not implemented automatically yet)
    if len(custom_bins) != 0:
        xmin = custom_bins[0]
        xmax = custom_bins[-1]
        #ymin = 0.
        #ymaqx = 0.09
        plt.xlim([0,400])
        #plt.ylim([0.06,0.15])

    # create legend and plot/font size
    ax.legend()
    ax.legend(loc="upper right", numpoints=1, frameon=False, prop={'size':14})

    # set the title of the figure
    if title != '':
        plt.title(title)

    # set the x axis ticks automatically
    ax.xaxis.set_major_locator(ticker.AutoLocator())
    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator())

    # save the figure
    print('saving the figure')
    # save the figure in PDF format
    if outputfiletag != '':
        infile = plot_type + '-' + outputfiletag + '_stacked.dat'
    else:
        infile = plot_type + '_stacked.dat'
    print('output in', infile.replace('.dat','.pdf'))
    plt.savefig(infile.replace('.dat','.pdf'), bbox_inches='tight')
    plt.close(fig)


# function to plot histograms: including the cross section normalization
# CrossSection_array contains ARRAYS of cross sections
# DATA_array contains ARRAYS of data for each event. Each array represents a different type of input (e.g. a run with different parameters, etc.).
# plot_type is simply the main name of the plot
# plotnames_multi has to be an array of equal size to DATA_array
# custom_bins can be provided for the desired observable
def histogram_multi_xsec(DATA_array, CrossSection_array, plot_type, plotnames_multi, xlabel='', ylabel='fraction/bin', nbins=50, title='', custom_bins=[], ylogbool=False, xlogbool=False):
    print('---')
    print('plotting', plot_type)

    # plot settings ########
    ylab = ylabel # the ylabel
    xlab = xlabel # the x label
    # log scale?
    ylog = ylogbool # whether to plot y in log scale
    xlog = xlogbool # whether to plot x in log scale

    # construct the axes for the plot
    # no need to modify this if you just need one plot
    gs = gridspec.GridSpec(4, 4)
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.grid(False)

    # loop over the DATA in the DATA_array
    # get the errors per bin and normalize so that we obtain fraction of events/bin
    dd = 0
    for DATA in DATA_array:
        if len(custom_bins) == 0:
            bins, edges = np.histogram(np.array(DATA), bins=nbins)
        else:
            bins, edges = np.histogram(np.array(DATA), bins=custom_bins)
        errors = np.divide(np.sqrt(bins), bins, out=np.zeros_like(np.sqrt(bins)), where=bins!=0.)
        bins = bins/float(len(DATA))
        errors = bins*errors
        #print(bins)
        #print(errors)
        left,right = edges[:-1],edges[1:]
        X = np.array([left,right]).T.flatten()
        Y = np.array([bins,bins]).T.flatten()*CrossSection_array[dd]


        plt.plot(X,Y, label=plotnames_multi[dd], color=next_color(), lw=1)
        #center = (edges[:-1] + edges[1:]) / 2
        #plt.errorbar(center, bins, yerr=errors, color=same_color(), lw=0, elinewidth=1, capsize=1)
        dd = dd+1


    # set the ticks, labels and limits etc.
    ax.set_ylabel(ylab, fontsize=20)
    ax.set_xlabel(xlab, fontsize=20)

    # choose x and y log scales
    if ylog:
        ax.set_yscale('log')
    else:
        ax.set_yscale('linear')
    if xlog:
        ax.set_xscale('log')
    else:
        ax.set_xscale('linear')

    # set the limits on the x and y axes if required below:
    # (this is not implemented automatically yet)
    if len(custom_bins) != 0:
        xmin = custom_bins[0]
        xmax = custom_bins[-1]
        #ymin = 0.
        #ymaqx = 0.09
        plt.xlim([xmin,xmax])
        #plt.ylim([0.06,0.15])

    # create legend and plot/font size
    ax.legend()
    ax.legend(loc="upper right", numpoints=1, frameon=False, prop={'size':14})

    # set the title of the figure
    if title != '':
        plt.title(title)

    # set the x axis ticks automatically
    ax.xaxis.set_major_locator(ticker.AutoLocator())
    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator())

    # save the figure
    print('saving the figure')
    # save the figure in PDF format
    if outputfiletag != '':
        infile = plot_type + '-' + outputfiletag + '.dat'
    else:
        infile = plot_type + '.dat'
    print('output in', infile.replace('.dat','.pdf'))
    plt.savefig(infile.replace('.dat','.pdf'), bbox_inches='tight')
    plt.close(fig)


# function to plot histograms: including the cross section normalization AND RATIO
# CrossSection_array contains ARRAYS of cross sections
# DATA_array contains ARRAYS of data for each event. Each array represents a different type of input (e.g. a run with different parameters, etc.).
# plot_type is simply the main name of the plot
# plotnames_multi has to be an array of equal size to DATA_array
# custom_bins can be provided for the desired observable
def histogram_multi_xsec_ratio(DATA_array, CrossSection_array, plot_type, plotnames_multi, xlabel='', ylabel='fraction/bin', nbins=50, title='', custom_bins=[], ylogbool=False, xlogbool=False):
    print('---')
    print('plotting', plot_type)

    # plot settings ########
    ylab = ylabel # the ylabel
    xlab = xlabel # the x label
    # log scale?
    ylog = ylogbool # whether to plot y in log scale
    xlog = xlogbool # whether to plot x in log scale

    # construct the axes for the plot
    # no need to modify this if you just need one plot
    fig = plt.figure(figsize=(8, 8))
    gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1], hspace=0.05)
    ax = fig.add_subplot(gs[0])
    ax_ratio = fig.add_subplot(gs[1], sharex=ax)
    ax.grid(False)

    # loop over the DATA in the DATA_array
    # get the errors per bin and normalize so that we obtain fraction of events/bin
    dd = 0

    Xlist = []
    Ylist = []
    for DATA in DATA_array:
        if len(custom_bins) == 0:
            bins, edges = np.histogram(np.array(DATA), bins=nbins)
        else:
            bins, edges = np.histogram(np.array(DATA), bins=custom_bins)
        errors = np.divide(np.sqrt(bins), bins, out=np.zeros_like(np.sqrt(bins)), where=bins!=0.)
        bins = bins/float(len(DATA))
        errors = bins*errors
        #print(bins)
        #print(errors)
        left,right = edges[:-1],edges[1:]
        X = np.array([left,right]).T.flatten()
        Y = np.array([bins,bins]).T.flatten()*CrossSection_array[dd]
        Xlist.append(X)
        Ylist.append(Y)

        plt.plot(X,Y, label=plotnames_multi[dd], color=next_color(), lw=1)
        #center = (edges[:-1] + edges[1:]) / 2
        #plt.errorbar(center, bins, yerr=errors, color=same_color(), lw=0, elinewidth=1, capsize=1)
        dd = dd+1

    Xref = Xlist[0]
    Yref = Ylist[0]
    for Xi in range(1,len(Xlist)):
        plt.plot(Xlist[Xi],Y/Yref, label='', color=next_color(), lw=1)


    # set the ticks, labels and limits etc.
    ax.set_ylabel(ylab, fontsize=20)
    ax_ratio.set_xlabel(xlab, fontsize=20)
    ax.tick_params(labelbottom=False)
    ax_ratio.axhline(1.0, color='gray', linestyle='--', linewidth=1)
    ax_ratio.set_ylim(0.0, 2.0)
    ax_ratio.xaxis.set_major_locator(ticker.AutoLocator())
    ax_ratio.xaxis.set_minor_locator(ticker.AutoMinorLocator())
    ax_ratio.set_ylabel('Ratio', fontsize=12)

    # choose x and y log scales
    if ylog:
        ax.set_yscale('log')
    else:
        ax.set_yscale('linear')
    if xlog:
        ax.set_xscale('log')
    else:
        ax.set_xscale('linear')

    # set the limits on the x and y axes if required below:
    # (this is not implemented automatically yet)
    if len(custom_bins) != 0:
        xmin = custom_bins[0]
        xmax = custom_bins[-1]
        #ymin = 0.
        #ymaqx = 0.09
        plt.xlim([xmin,xmax])
        #plt.ylim([0.06,0.15])

    # create legend and plot/font size
    ax.legend()
    ax.legend(loc="upper right", numpoints=1, frameon=False, prop={'size':14})

    # set the title of the figure
    if title != '':
        plt.title(title)

    # set the x axis ticks automatically
    ax.xaxis.set_major_locator(ticker.AutoLocator())
    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator())

    # save the figure
    print('saving the figure')
    # save the figure in PDF format
    if outputfiletag != '':
        infile = plot_type + '-' + outputfiletag + '.dat'
    else:
        infile = plot_type + '.dat'
    print('output in', infile.replace('.dat','.pdf'))
    plt.savefig(infile.replace('.dat','.pdf'), bbox_inches='tight')
    plt.close(fig)
def histogram_multi_xsec_ratio(DATA_array, CrossSection_array, plot_type, plotnames_multi,
                               xlabel='', ylabel='fraction/bin', nbins=50, title='',
                               custom_bins=[], ylogbool=False, xlogbool=False):

    print('---')
    print('plotting', plot_type)

    fig = plt.figure(figsize=(8, 8))
    gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1], hspace=0.05)
    ax = fig.add_subplot(gs[0])
    ax_ratio = fig.add_subplot(gs[1], sharex=ax)

    Xlist, Ylist = [], []
    reset_color()

    for dd, DATA in enumerate(DATA_array):
        DATA = np.asarray(DATA, dtype=float)

        # Optional: drop NaNs/Infs (helps esp. mall if you returned np.nan)
        DATA = DATA[np.isfinite(DATA)]

        if len(custom_bins) == 0:
            counts, edges = np.histogram(DATA, bins=nbins)
        else:
            counts, edges = np.histogram(DATA, bins=custom_bins)

        if len(DATA) == 0:
            # nothing to plot
            continue

        bins = counts / float(len(DATA))  # fraction per bin
        left, right = edges[:-1], edges[1:]
        X = np.array([left, right]).T.flatten()
        Y = np.array([bins, bins]).T.flatten() * CrossSection_array[dd]

        Xlist.append(X)
        Ylist.append(Y)

        ax.plot(X, Y, label=plotnames_multi[dd], color=next_color(), lw=1)

    # Ratio: everything / reference(0)
    if len(Ylist) >= 2:
        Xref, Yref = Xlist[0], Ylist[0]
        for i in range(1, len(Ylist)):
            Yi = Ylist[i]
            # safe division
            ratio = np.divide(Yi, Yref, out=np.zeros_like(Yi), where=(Yref != 0.0))
            ax_ratio.plot(Xlist[i], ratio, color=next_color(), lw=1)

    ax.set_ylabel(ylabel, fontsize=20)
    ax_ratio.set_xlabel(xlabel, fontsize=20)
    ax.tick_params(labelbottom=False)

    ax_ratio.axhline(1.0, color='gray', linestyle='--', linewidth=1)
    ax_ratio.set_ylim(0.0, 2.0)
    ax_ratio.set_ylabel('Ratio', fontsize=12)

    if ylogbool:
        ax.set_yscale('log')
    if xlogbool:
        ax.set_xscale('log')
        ax_ratio.set_xscale('log')

    if len(custom_bins) != 0:
        ax.set_xlim(custom_bins[0], custom_bins[-1])

    ax.legend(loc="upper right", numpoints=1, frameon=False, prop={'size': 14})

    if title:
        ax.set_title(title)

    ax.xaxis.set_major_locator(ticker.AutoLocator())
    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator())
    ax_ratio.xaxis.set_major_locator(ticker.AutoLocator())
    ax_ratio.xaxis.set_minor_locator(ticker.AutoMinorLocator())

    if outputfiletag != '':
        infile = plot_type + '-' + outputfiletag + '.pdf'
    else:
        infile = plot_type + '.pdf'

    print('output in', infile)
    fig.savefig(infile, bbox_inches='tight')
    plt.close(fig)


# function to plot histograms
# DATA_array contains ARRAYS of data for each event. Each array represents a different type of input (e.g. a run with different parameters, etc.).
# plot_type is simply the main name of the plot
# plotnames_multi has to be an array of equal size to DATA_array
# custom_bins can be provided for the desired observable
def histogram_multi(DATA_array, plot_type, plotnames_multi, xlabel='', ylabel='fraction/bin', nbins=50, title='', custom_bins=[], ylogbool=False, xlogbool=False):
    print('---')
    print('plotting', plot_type)

    # plot settings ########
    ylab = ylabel # the ylabel
    xlab = xlabel # the x label
    # log scale?
    ylog = ylogbool # whether to plot y in log scale
    xlog = xlogbool # whether to plot x in log scale

    # construct the axes for the plot
    # no need to modify this if you just need one plot
    gs = gridspec.GridSpec(4, 4)
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.grid(False)

    # loop over the DATA in the DATA_array
    # get the errors per bin and normalize so that we obtain fraction of events/bin
    dd = 0
    for DATA in DATA_array:
        if len(custom_bins) == 0:
            bins, edges = np.histogram(np.array(DATA), bins=nbins)
        else:
            bins, edges = np.histogram(np.array(DATA), bins=custom_bins)
        errors = np.divide(np.sqrt(bins), bins, out=np.zeros_like(np.sqrt(bins)), where=bins!=0.)
        bins = bins/float(len(DATA))
        errors = bins*errors
        #print(bins)
        #print(errors)
        left,right = edges[:-1],edges[1:]
        X = np.array([left,right]).T.flatten()
        Y = np.array([bins,bins]).T.flatten()
        plt.plot(X,Y, label=plotnames_multi[dd], color=next_color(), lw=1)
        center = (edges[:-1] + edges[1:]) / 2
        plt.errorbar(center, bins, yerr=errors, color=same_color(), lw=0, elinewidth=1, capsize=1)
        dd = dd+1


    # set the ticks, labels and limits etc.
    ax.set_ylabel(ylab, fontsize=20)
    ax.set_xlabel(xlab, fontsize=20)

    # choose x and y log scales
    if ylog:
        ax.set_yscale('log')
    else:
        ax.set_yscale('linear')
    if xlog:
        ax.set_xscale('log')
    else:
        ax.set_xscale('linear')

    # set the limits on the x and y axes if required below:
    # (this is not implemented automatically yet)
    #xmin = 0.
    #xmax = 1500.
    #ymin = 0.
    #ymax = 0.09
    #plt.xlim([0,400])
    #plt.ylim([0.06,0.15])

    # create legend and plot/font size
    ax.legend()
    ax.legend(loc="upper right", numpoints=1, frameon=False, prop={'size':14})

    # set the title of the figure
    if title != '':
        plt.title(title)

    # save the figure
    print('saving the figure')
    # save the figure in PDF format
    if outputfiletag != '':
        infile = plot_type + '-' + outputfiletag + '.dat'
    else:
        infile = plot_type + '.dat'
    print('output in', infile.replace('.dat','.pdf'))
    plt.savefig(infile.replace('.dat','.pdf'), bbox_inches='tight')
    plt.close(fig)

# function to read lhe files in and grab the particle momenta for each event
# it also grabs the weight of each event, as well as the multiple weights, if present
# the return variables are: events, in which each entry is a set of particle 4-momenta in the format:
# [id, status, px, py, pz, e, m] -> id is the PDG id, status is the LHE status (i.e. incoming: -1, final: 1)
# weights contains the weight of each event
# multiweights contains the multiple weights of each event
def readlhefile(infile):
    if infile.endswith('.gz'):
        my_open = gzip.open
    else:
        my_open = open
    infile_read = my_open(infile, 'rt')
    numevents = 0
    reading_event = False
    events = []
    weights = []
    multiweights = []
    for line in infile_read:
        if '<event' in line:
            particles = []
            multiweight = {}
            #print('reading new event')
            numevents = numevents + 1
            reading_event = True
            continue
        if reading_event is True:
            if '</event>' in line:
                reading_event = False
                events.append(particles)
                weights.append(weight)
                multiweights.append(multiweight)
            #print(line, len(line.split()))
            if len(line.split()) == 6:
                weight = float(line.split()[2])
            if len(line.split()) == 13:
                particles.append(read_momenta(line))
            if len(line.split()) == 4:
                multiweight[line.split()[1].replace('id=', '').replace('>', '').replace("'", '')] = float(line.split()[2])
                #print('multiweight[', line.split()[1].replace('id=', '').replace('>', '').replace("'", ''), ']=', line.split()[2])

    return events, weights, multiweights

# read the particle information for the given particle line in the LHE file
def read_momenta(inputline):
    id = int(inputline.split()[0])
    status = int(inputline.split()[1])
    px = float(inputline.split()[6])
    py = float(inputline.split()[7])
    pz = float(inputline.split()[8])
    e = float(inputline.split()[9])
    m = float(inputline.split()[10])
    return [id, status, px, py, pz, e, m]


# invariant mass calculation for 4b + 2j
def calc_mall(bquarks, light):
    """
    Compute invariant mass of the combined system of all input particles.

    Inputs:
      bquarks: list of [pdgid, px, py, pz, E]
      light:   list of [pdgid, px, py, pz, E]

    Returns:
      mall (float): invariant mass sqrt(E^2 - |p|^2) in the same units as inputs.
                    Returns np.nan if there are no particles.
    """
    # Combine both lists
    particles = (bquarks or []) + (light or [])
    if len(particles) == 0:
        return np.nan  # or 0.0, depending on what you prefer

    # Sum four-momentum components
    px = 0.0
    py = 0.0
    pz = 0.0
    E  = 0.0

    for p in particles:
        # p = [pdgid, px, py, pz, E]
        px += p[1]
        py += p[2]
        pz += p[3]
        E  += p[4]

    m2 = E*E - (px*px + py*py + pz*pz)

    # Numerical safety: small negative m2 can happen from floating point rounding
    if m2 < 0.0 and m2 > -1e-12:
        m2 = 0.0

    # If it's truly negative (unphysical for summed final states, but possible if inputs are inconsistent)
    if m2 < 0.0:
        return np.nan  # or return -np.sqrt(-m2) if you want a signed diagnostic

    return np.sqrt(m2)

############################################################
# Define your ANALYSIS function here!
# The example looks for the new particle with pdg id "99925"
# and calculates its transverse momentum.
# For each observable we wish to return, we must add it to
# the dictionary "output_dictionary" as in the example below.
#############################################################
def analyze(events, weights):
    # a dictionary that contains the arrays that we wish to plot
    output_dictionary = {}
    # construct the observables by putting emtpy arrays into the dictionary:
    output_dictionary['ptb'] = []
    output_dictionary['ptlight'] = []
    output_dictionary['mall'] = []
    # loop over the particles in the event:
    for iev, particles in tqdm(enumerate(events)):
        # array for light quarks or b quarks
        bquarks = []
        light = []
        for p in particles:
            if abs(p[0])==5:
                bquarks.append([p[0], p[2], p[3], p[4], p[5]])
                ptb = np.sqrt(p[2]**2 + p[3]**2)
                output_dictionary['ptb'].append(ptb)
            if abs(p[0])==21 or abs(p[0])<5:
                light.append([p[0], p[2], p[3], p[4], p[5]])
                ptlight = np.sqrt(p[2]**2 + p[3]**2)
                output_dictionary['ptlight'].append(ptlight)
        mall = calc_mall(bquarks, light)
        output_dictionary['mall'].append(mall)

    return output_dictionary


#######################################
# PERFORM THE ANALYSIS AND PLOT HERE:
#######################################

# read the LHE File
print('Reading', inputfile)
events, weights, multiweights = readlhefile(inputfile)
# analyze the events by passing them to the analysis fuinction defined above
output = analyze(events, weights)

if len(sys.argv) > 2:
    print('Reading', inputfile2)
    events2, weights2, multiweights2 = readlhefile(inputfile2)
    # analyze the events by passing them to the analysis fuinction defined above
    output2 = analyze(events2, weights2)

if len(sys.argv) > 3:
    print('Reading', inputfile3)
    events3, weights3, multiweights3 = readlhefile(inputfile3)
    # analyze the events by passing them to the analysis fuinction defined above
    output3 = analyze(events3, weights3)

print("len(sys.argv)=", len(sys.argv))

CrossSections = [1,1]
# plot all the variables in the output dictionary.
# here as an example we are plotting the heavy scalar pT.
# Note that "histogram_multi" takes as input in DATA_array an array of data points,
# hence the extra [] there and in the plotnames_multi
if len(sys.argv) == 3:
    # plots with ratio:
    histogram_multi_xsec_ratio([output['ptb'], output2['ptb']], CrossSections, 'ptb', ['ALPGEN', 'MG5'], r'$p_{Tb}$ [GeV]', ylabel=r'$1/\sigma \mathrm{d}\sigma/\mathrm{d}p_{Tb}$', title=r'$pp \rightarrow b\bar{b} b \bar{b} j j$', custom_bins=np.arange(20,1000, 40), ylogbool=True)
    histogram_multi_xsec_ratio([output['ptlight'], output2['ptlight']], CrossSections, 'ptlight', ['ALPGEN', 'MG5'], r'$p_{Tj}$ [GeV]', ylabel=r'$1/\sigma \mathrm{d}\sigma/\mathrm{d}p_{Tj}$', title=r'$pp \rightarrow b\bar{b} b \bar{b} j j$', custom_bins=np.arange(20,1000, 40), ylogbool=True)
    histogram_multi_xsec_ratio([output['mall'], output2['mall']], CrossSections, 'mall', ['ALPGEN', 'MG5'], r'$m_{4b2j}$ [GeV]', ylabel=r'$1/\sigma \mathrm{d}\sigma/\mathrm{d}m_{4b2j}$', title=r'$pp \rightarrow b\bar{b} b \bar{b} j j$', custom_bins=np.arange(200,4000, 100), ylogbool=True)


CrossSections = [1,1,1]
if len(sys.argv) == 4:
    # plots with ratio:
    histogram_multi_xsec_ratio([output['ptb'], output2['ptb'], output3['ptb']], CrossSections, 'ptb', ['ALPGEN', 'MG5', 'Sherpa'], r'$p_{Tb}$ [GeV]', ylabel=r'$1/\sigma \mathrm{d}\sigma/\mathrm{d}p_{Tb}$', title=r'$pp \rightarrow b\bar{b} b \bar{b} j j$', custom_bins=np.arange(20,1000, 40), ylogbool=True)
    histogram_multi_xsec_ratio([output['ptlight'], output2['ptlight'], output3['ptlight']], CrossSections, 'ptlight', ['ALPGEN', 'MG5', 'Sherpa'], r'$p_{Tj}$ [GeV]', ylabel=r'$1/\sigma \mathrm{d}\sigma/\mathrm{d}p_{Tj}$', title=r'$pp \rightarrow b\bar{b} b \bar{b} j j$', custom_bins=np.arange(20,1000, 40), ylogbool=True)
    histogram_multi_xsec_ratio([output['mall'], output2['mall'], output3['mall']], CrossSections, 'mall', ['ALPGEN', 'MG5', 'Sherpa'], r'$m_{4b2j}$ [GeV]', ylabel=r'$1/\sigma \mathrm{d}\sigma/\mathrm{d}m_{4b2j}$', title=r'$pp \rightarrow b\bar{b} b \bar{b} j j$', custom_bins=np.arange(200,4000, 40), ylogbool=True)
