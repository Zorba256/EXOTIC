import logging
import numpy as np
import lmfit as lm
log = logging.getLogger(__name__)
import matplotlib.pyplot as plt
import ldtk
from ldtk import LDPSetCreator, BoxcarFilter
from ldtk.ldmodel import LinearModel, QuadraticModel, NonlinearModel


class LDPSet(ldtk.LDPSet):
    '''
    A. NIESSNER: INLINE HACK TO ldtk.LDPSet
    '''
    @staticmethod
    def is_mime(): return True

    @property
    def profile_mu(self): return self._mu
    pass
setattr(ldtk, 'LDPSet', LDPSet)
setattr(ldtk.ldtk, 'LDPSet', LDPSet)
# --------------------------------- ----------------------------------
# -- CREATE LD GRID -- -----------------------------------------------
def createldgrid(minmu, maxmu, orbp,
                 ldmodel='nonlinear', phoenixmin=1e-1,
                 segmentation=int(10), verbose=False):
    '''
    G. ROUDIER: Wrapper around LDTK downloading tools
    LDTK: Parviainen et al. https://github.com/hpparvi/ldtk
    '''
    tstar = orbp['T*']
    terr = np.sqrt(abs(orbp['T*_uperr']*orbp['T*_lowerr']))
    fehstar = orbp['FEH*']
    feherr = np.sqrt(abs(orbp['FEH*_uperr']*orbp['FEH*_lowerr']))
    loggstar = orbp['LOGG*']
    loggerr = np.sqrt(abs(orbp['LOGG*_uperr']*orbp['LOGG*_lowerr']))
    log.warning('>-- Temperature: %s +/- %s', str(tstar), str(terr))
    log.warning('>-- Metallicity: %s +/- %s', str(fehstar), str(feherr))
    log.warning('>-- Surface Gravity: %s +/- %s', str(loggstar), str(loggerr))
    niter = int(len(minmu)/segmentation) + 1
    allcl = None
    allel = None
    out = {}
    avmu = [np.mean([mm, xm]) for mm, xm in zip(minmu, maxmu)]
    for i in np.arange(niter):
        loweri = i*segmentation
        upperi = (i+1)*segmentation
        if i == (niter-1): upperi = len(avmu)
        munm = 1e3*np.array(avmu[loweri:upperi])
        munmmin = 1e3*np.array(minmu[loweri:upperi])
        munmmax = 1e3*np.array(maxmu[loweri:upperi])
        filters = [BoxcarFilter(str(mue), mun, mux)
                   for mue, mun, mux in zip(munm, munmmin, munmmax)]
        sc = LDPSetCreator(teff=(tstar, terr), logg=(loggstar, loggerr),
                           z=(fehstar, feherr), filters=filters)
        ps = sc.create_profiles(nsamples=int(1e4))
        itpfail = False
        for testprof in ps.profile_averages:
            if np.all(~np.isfinite(testprof)): itpfail = True
            pass
        nfail = 1e0
        while itpfail:
            nfail *= 2
            sc = LDPSetCreator(teff=(tstar, nfail*terr), logg=(loggstar, loggerr),
                               z=(fehstar, feherr), filters=filters)
            ps = sc.create_profiles(nsamples=int(1e4))
            itpfail = False
            for testprof in ps.profile_averages:
                if np.all(~np.isfinite(testprof)): itpfail = True
                pass
            pass
        cl, el = ldx(ps.profile_mu, ps.profile_averages, ps.profile_uncertainties,
                     mumin=phoenixmin, debug=verbose, model=ldmodel)
        if allcl is None: allcl = cl
        else: allcl = np.concatenate((allcl, cl), axis=0)
        if allel is None: allel = el
        else: allel = np.concatenate((allel, el), axis=0)
        pass
    allel[allel > 1.] = 0.
    allel[~np.isfinite(allel)] = 0.
    out['MU'] = avmu
    out['LD'] = allcl.T
    out['ERR'] = allel.T
    for i in range(0,len(allcl.T)):
        log.warning('>-- LD%s: %s +/- %s',
                    str(int(i)), str(float(allcl.T[i])), str(float(allel.T[i])))
        pass
    return out
# -------------------- -----------------------------------------------
# -- LDX -- ----------------------------------------------------------
def ldx(psmu, psmean, psstd, mumin=1e-1, debug=False, model='nonlinear'):
    '''
    G. ROUDIER: Limb darkening coefficient retrievial on PHOENIX GRID models,
    OPTIONAL mumin set up on HAT-P-41 stellar class
    '''
    mup=np.array(psmu).copy()
    prfs=np.array(psmean).copy()
    sprfs=np.array(psstd).copy()
    nwave=prfs.shape[0]
    select=(mup > mumin)
    fitmup=mup[select]
    fitprfs=prfs[:, select]
    fitsprfs=sprfs[:, select]
    cl=[]
    el=[]
    params=lm.Parameters()
    params.add('gamma1', value=1e-1)
    params.add('gamma2', value=5e-1)
    params.add('gamma3', value=1e-1)
    params.add('gamma4', expr='1 - gamma1 - gamma2 - gamma3')
    if debug: plt.figure()
    for iwave in np.arange(nwave):
        select = fitsprfs[iwave] == 0e0
        if True in select: fitsprfs[iwave][select] = 1e-10
        if model == 'linear':
            params['gamma1'].value = 0
            params['gamma1'].vary = False
            params['gamma3'].value = 0
            params['gamma3'].vary = False
            params['gamma4'].value = 0
            params['gamma4'].vary = False
            out=lm.minimize(lnldx, params,
                            args=(fitmup, fitprfs[iwave], fitsprfs[iwave]))
            cl.append([out.params['gamma1'].value])
            el.append([out.params['gamma1'].stderr])
            pass
        if model == 'quadratic':
            params['gamma1'].value = 0
            params['gamma1'].vary = False
            params['gamma3'].value = 0
            params['gamma3'].vary = False
            out=lm.minimize(qdldx, params,
                            args=(mup, prfs[iwave], sprfs[iwave]))
            cl.append([out.params['gamma2'].value, out.params['gamma4'].value])
            el.append([out.params['gamma2'].stderr, out.params['gamma4'].stderr])
            pass
        if model == 'nonlinear':
            out = lm.minimize(nlldx, params,
                              args=(fitmup, fitprfs[iwave], fitsprfs[iwave]))
            cl.append([out.params['gamma1'].value, out.params['gamma2'].value,
                       out.params['gamma3'].value, out.params['gamma4'].value])
            el.append([out.params['gamma1'].stderr, out.params['gamma2'].stderr,
                       out.params['gamma3'].stderr, out.params['gamma4'].stderr])
            pass
        if debug:
            plt.plot(mup, prfs[iwave], 'k^')
            plt.errorbar(fitmup, fitprfs[iwave], yerr=fitsprfs[iwave], ls='None')
            if model == 'linear': plt.plot(fitmup, lnldx(out.params, fitmup))
            if model == 'quadratic': plt.plot(fitmup, qdldx(out.params, fitmup))
            if model == 'nonlinear': plt.plot(fitmup, nlldx(out.params, fitmup))
            pass
        pass
    if debug:
        plt.ylabel('$I(\\mu)$')
        plt.xlabel('$\\mu$')
        plt.title(model)
        plt.show()
        pass
    return np.array(cl), np.array(el)
# --------- ----------------------------------------------------------
# -- LNLDX -- --------------------------------------------------------
def lnldx(params, x, data=None, weights=None):
    '''
    G. ROUDIER: Linear law
    '''
    gamma1=params['gamma1'].value
    model=LinearModel.evaluate(x, np.array(gamma1))
    if data is None: return model
    if weights is None: return data - model
    return (data - model)/weights
# ----------- --------------------------------------------------------
# -- QDLDX -- --------------------------------------------------------
def qdldx(params, x, data=None, weights=None):
    '''
    G. ROUDIER: Quadratic law
    '''
    gamma1 = params['gamma2'].value
    gamma2 = params['gamma4'].value
    model = QuadraticModel.evaluate(x, np.array((gamma1, gamma2)))
    if data is None: return model
    if weights is None: return data - model
    return (data - model)/weights
# ----------- --------------------------------------------------------
# -- NLLDX -- --------------------------------------------------------
def nlldx(params, x, data=None, weights=None):
    '''
    G. ROUDIER: Non Linear law
    '''
    gamma1 = params['gamma1'].value
    gamma2 = params['gamma2'].value
    gamma3 = params['gamma3'].value
    gamma4 = params['gamma4'].value
    model = NonlinearModel.evaluate(x, np.array((gamma1, gamma2, gamma3, gamma4)))
    if data is None: return model
    if weights is None: return data - model
    return (data - model)/weights


class LimbDarkening:
    def __init__(self, teff=None, teffpos=None, teffneg=None, met=None, metpos=None, metneg=None,
                 logg=None, loggpos=None, loggneg=None, wl_min=None, wl_max=None, filter_type=None):
        self.priors = {'T*': teff, 'T*_uperr': teffpos, 'T*_lowerr': teffneg,
                       'FEH*': met, 'FEH*_uperr': metpos, 'FEH*_lowerr': metneg,
                       'LOGG*': logg, 'LOGG*_uperr': loggpos, 'LOGG*_lowerr': loggneg}
        self.filter_type = filter_type
        self.wl_min = wl_min
        self.wl_max = wl_max
        self.ld0 = self.ld1 = self.ld2 = self.ld3 = None
        # Source for FWHM band wavelengths (units: nm): https://www.aavso.org/filters
                     # Near-Infrared
        self.fwhm = {('J NIR 1.2micron', 'J'): (1040.00, 1360.00), ('H NIR 1.6micron', 'H'): (1420.00, 1780.00),
                     ('K NIR 2.2micron', 'K'): (2015.00, 2385.00),
                     # Sloan
                     ('Sloan u', 'SU'): (321.80, 386.80), ('Sloan g', 'SG'): (402.50, 551.50),
                     ('Sloan r', 'SR'): (553.10, 693.10), ('Sloan i', 'SI'): (697.50, 827.50),
                     ('Sloan z', 'SZ'): (841.20, 978.20),
                     # Stromgren
                     ('Stromgren b', 'STB'): (459.55, 478.05), ('Stromgren y', 'STY'): (536.70, 559.30),
                     ('Stromgren Hbw', 'STHBW'): (481.50, 496.50), ('Stromgren Hbn', 'STHBN'): (487.50, 484.50),
                     # Johnson
                     ('Johnson U', 'U'): (333.80, 398.80), ('Johnson B', 'B'): (391.60, 480.60),
                     ('Johnson V', 'V'): (502.80, 586.80), ('Johnson R', 'RJ'): (590.00, 810.00),
                     ('Johnson I', 'IJ'): (780.00, 1020.00),
                     # Cousins
                     ('Cousins R', 'R'): (561.70, 719.70), ('Cousins I', 'I'): (721.00, 875.00),
                     # MObs Clear Filter, Source: Martin Fowler
                     ('MObs CV', 'CV'): (350.00, 850.00),
                     # Astrodon CBB: George Silvis: https://astrodon.com/products/astrodon-exo-planet-filter/
                     ('Astrodon ExoPlanet-BB', 'CBB'): (500.00, 1000.00),
                     # LCO, Source: Kalee Tock & Michael Fitzgerald, https://lco.global/observatory/instruments/filters/
                     ('LCO Bessell B', 'N/A'): (391.60, 480.60), ('LCO Bessell V', 'N/A'): (502.80, 586.80),
                     ('LCO Pan-STARRS w', 'N/A'): (404.20, 845.80), ('LCO Pan-STARRS w', 'N/A'): (404.20, 845.80),
                     ('LCO Pan-STARRS zs', 'N/A'): (818.00, 922.00), ("LCO SDSS g'", 'N/A'): (402.00, 552.00),
                     ("LCO SDSS r'", 'N/A'): (552.00, 691.00), ("LCO SDSS i'", 'N/A'): (690.00, 819.00)}
    def nonlinear_ld(self):
        self._standard_list()
        if self.filter_type and not (self.wl_min or self.wl_max):
            self._standard()
        elif self.wl_min or self.wl_max:
            self._custom()
        else:
            option = user_input('\nWould you like EXOTIC to calculate your limb darkening parameters '
                                'with uncertainties? (y/n): ', type_=str, val1='y', val2='n')
            if option == 'y':
                opt = user_input('Please enter 1 to use a standard filter or 2 for a customized filter: ',
                                 type_=int, val1=1, val2=2)
                if opt == 1:
                    self._standard()
                elif opt == 2:
                    self._custom()
            else:
                self._user_entered()
        return self.ld0, self.ld1, self.ld2, self.ld3, self.filter_type
    def _standard_list(self):
        print('\n\n***************************')
        print('Limb Darkening Coefficients')
        print('***************************')
        print('\nStandard bands available to filter for limb darkening parameters (https://www.aavso.org/filters)'
              '\nas well as filters for MObs and LCO (0.4m telescope) datasets:\n')
        for key, value in self.fwhm.items():
            print('\t{}: {} - ({:.2f}-{:.2f}) nm'.format(key[1], key[0], value[0], value[1]))
    def _standard(self):
        while True:
            try:
                if not self.filter_type:
                    self.filter_type = input('\nPlease enter in the filter type (EX: Johnson V, V, STB, RJ): ')
                for key, value in self.fwhm.items():
                    if self.filter_type in (key[0], key[1]) and self.filter_type != 'N/A':
                        self.filter_type = (key[0], key[1])
                        break
                else:
                    raise KeyError
                break
            except KeyError:
                # changed for citisens
                self.filter_type = 'V'
                # print('\nError: The entered filter is not in the provided list of standard filters.')
                # self.filter_type = None
        self.wl_min = self.fwhm[self.filter_type][0]
        self.wl_max = self.fwhm[self.filter_type][1]
        self.filter_type = self.filter_type[1]
        self._calculate_ld()
    def _custom(self):
        self.filter_type = 'N/A'
        if not self.wl_min:
            self.wl_min = float(input('FWHM Minimum wavelength (nm): '))
        if not self.wl_max:
            self.wl_max = float(input('FWHM Maximum wavelength (nm): '))
        self._calculate_ld()
    def _user_entered(self):
        self.filter_type = input('\nEnter in your filter name: ')
        ld_0 = user_input('\nEnter in your first nonlinear term: ', type_=float)
        ld0_unc = user_input('Enter in your first nonlinear term uncertainty: ', type_=float)
        ld_1 = user_input('\nEnter in your second nonlinear term: ', type_=float)
        ld1_unc = user_input('Enter in your second nonlinear term uncertainty: ', type_=float)
        ld_2 = user_input('\nEnter in your third nonlinear term: ', type_=float)
        ld2_unc = user_input('Enter in your third nonlinear term uncertainty: ', type_=float)
        ld_3 = user_input('\nEenter in your fourth nonlinear term: ', type_=float)
        ld3_unc = user_input('Enter in your fourth nonlinear term uncertainty: ', type_=float)
        self.ld0, self.ld1, self.ld2, self.ld3 = (ld_0, ld0_unc), (ld_1, ld1_unc), (ld_2, ld2_unc), (ld_3, ld3_unc)
    def _calculate_ld(self):
        self.wl_min = [self.wl_min / 1000]
        self.wl_max = [self.wl_max / 1000]
        ld_params = createldgrid(np.array(self.wl_min), np.array(self.wl_max), self.priors)
        self.ld0 = ld_params['LD'][0][0], ld_params['ERR'][0][0]
        self.ld1 = ld_params['LD'][1][0], ld_params['ERR'][1][0]
        self.ld2 = ld_params['LD'][2][0], ld_params['ERR'][2][0]
        self.ld3 = ld_params['LD'][3][0], ld_params['ERR'][3][0]