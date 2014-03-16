#
# wcsmod.py -- module wrapper for WCS calculations.
#
# Eric Jeschke (eric@naoj.org)
#
# Copyright (c) Eric R. Jeschke.  All rights reserved.
# This is open-source software licensed under a BSD license.
# Please see the file LICENSE.txt for details.
#
"""
We are lucky to have several possible choices for a python WCS package
compatible with Ginga: astlib, kapteyn, starlink and astropy.
kapteyn and astropy wrap Doug Calabretta's "WCSLIB", astLib wraps
Doug Mink's "wcstools", and I'm not sure what starlink uses (their own?).

Note that astlib requires pyfits (or astropy) in order to create a WCS
object from a FITS header. 

To force the use of one, do:

    from ginga.util import wcsmod
    wcsmod.use('kapteyn')

before you load any images.  Otherwise Ginga will try to pick one for
you.
"""

import math
import re
import numpy

# Module variables that get configured at module load time
# or when use() is called
coord_types = []
display_types = ['sexagesimal', 'degrees']
wcs_configured = False

have_kapteyn = False
have_astlib = False
have_pywcs = False
have_astropy = False
have_starlink = False
WCS = None

class WCSError(Exception):
    pass

def use(wcspkg, raise_err=True):
    global coord_types, wcs_configured, WCS, \
           have_kapteyn, kapwcs, \
           have_astlib, astWCS, astCoords, \
           have_starlink, Ast, Atl, \
           have_astropy, pywcs, coordinates, units
    
    if wcspkg == 'kapteyn':
        try:
            from kapteyn import wcs as kapwcs
            coord_types = ['icrs', 'fk5', 'fk4', 'galactic', 'ecliptic']
            have_kapteyn = True
            wcs_configured = True
            WCS = KapteynWCS
            return True

        except ImportError as e:
            if raise_err:
                raise
        return False
    
    elif wcspkg == 'starlink':
        try:
            import starlink.Ast as Ast
            import starlink.Atl as Atl
            coord_types = ['icrs', 'fk5', 'fk4', 'galactic', 'ecliptic']
            have_starlink = True
            wcs_configured = True
            WCS = StarlinkWCS
            return True

        except ImportError as e:
            if raise_err:
                raise
        return False
    
    elif wcspkg == 'astlib':
        try:
            from astLib import astWCS, astCoords
            # astlib requires pyfits (or astropy) in order
            # to create a WCS object from a FITS header.
            try:
                from astropy.io import fits as pyfits
            except ImportError:
                try:
                    import pyfits
                except ImportError:
                    raise ImportError("Need pyfits module to use astLib WCS")

            astWCS.NUMPY_MODE = True
            coord_types = ['j2000', 'b1950', 'galactic']
            have_astlib = True
            wcs_configured = True
            WCS = AstLibWCS
            return True

        except ImportError as e:
            if raise_err:
                raise
        return False

    elif wcspkg == 'astropy':
        try:
            import astropy.wcs as pywcs
            from astropy.io import fits as pyfits
            have_pywcs = True
        except ImportError:
            try:
                import pywcs
                have_pywcs = True
            except ImportError as e:
                if raise_err:
                    raise

        try:
            from astropy import coordinates
            from astropy import units
            have_astropy = True
            wcs_configured = True
            coord_types = ['icrs', 'fk5', 'fk4', 'galactic']
            WCS = AstropyWCS
            return True

        except ImportError as e:
            if raise_err:
                raise
        return False

    elif wcspkg == 'barebones':
        coord_types = ['fk5']
        WCS = BareBonesWCS
    return False
        

class BaseWCS(object):

    def get_keyword(self, key):
        return self.header[key]
        
    def get_keywords(self, *args):
        return map(lambda key: self.header[key], args)
        
    def fix_bad_headers(self):
        """Fix up bad headers that cause problems for WCSLIB.
        Subclass can override this method to fix up issues with the
        header for problem FITS files.
        """
        # WCSLIB doesn't like "nonstandard" units
        unit = self.header.get('CUNIT1', 'deg')
        if unit.upper() == 'DEGREE':
            #self.header.update('CUNIT1', 'deg')
            self.header['CUNIT1'] = 'deg'
        unit = self.header.get('CUNIT2', 'deg')
        if unit.upper() == 'DEGREE':
            #self.header.update('CUNIT2', 'deg')
            self.header['CUNIT2'] = 'deg'


class AstropyWCS(BaseWCS):
    """A WCS interface for astropy.wcs
    You need to install python module 'astropy'

        http://pypi.python.org/pypi/astropy

    if you want to use this version.
    """

    def __init__(self, logger):
        super(AstropyWCS, self).__init__()

        if not have_astropy:
            raise WCSError("Please install module 'astropy' first!")
        self.logger = logger
        self.header = None
        self.wcs = None
        self.coordsys = 'raw'
        self.coord_table = {
            'icrs': coordinates.ICRSCoordinates,
            'fk5': coordinates.FK5Coordinates,
            'fk4': coordinates.FK4Coordinates,
            'galactic': coordinates.GalacticCoordinates,
            #'azel': coordinates.HorizontalCoordinates,
            }
        self.kind = 'astropy/WCSLIB'

    def load_header(self, header, fobj=None):
        ## if isinstance(header, pyfits.Header):
        ##     self.header = header
        ## else:
        ##     # pywcs only operates on pyfits headers
        ##     self.header = pyfits.Header()
        ##     for kwd in header.keys():
        ##         try:
        ##             bnch = header.get_card(kwd)
        ##             self.header.update(kwd, bnch.value, comment=bnch.comment)
        ##         except Exception, e:
        ##             self.logger.warn("Error setting keyword '%s': %s" % (
        ##                     kwd, str(e)))
        self.header = {}
        # Seems pyfits header objects are not perfectly duck-typed as dicts
        #self.header.update(header)
        for key, value in header.items():
            self.header[key] = value

        self.fix_bad_headers()
        
        try:
            self.wcs = pywcs.WCS(self.header, fobj=fobj, relax=True)

            self.coordsys = choose_coord_system(self.header)
        except Exception, e:
            self.logger.error("Error making WCS object: %s" % (str(e)))
            self.wcs = None

    def pixtoradec(self, idxs, coords='data'):

        if coords == 'data':
            origin = 0
        else:
            origin = 1
        pixcrd = numpy.array([idxs], numpy.float_)
        try:
            #sky = self.wcs.wcs_pix2sky(pixcrd, origin)
            #sky = self.wcs.all_pix2sky(pixcrd, origin)
            # astropy only?
            sky = self.wcs.all_pix2world(pixcrd, origin)

        except Exception, e:
            self.logger.error("Error calculating pixtoradec: %s" % (str(e)))
            raise WCSError(e)
        
        ra_deg = float(sky[0, 0])
        dec_deg = float(sky[0, 1])

        return ra_deg, dec_deg
    
    def radectopix(self, ra_deg, dec_deg, coords='data', naxispath=None):

        if coords == 'data':
            origin = 0
        else:
            origin = 1

        args = [ra_deg, dec_deg]
        if naxispath:
            args += [0] * len(naxispath)
        skycrd = numpy.array([args], numpy.float_)

        try:
            #pix = self.wcs.wcs_sky2pix(skycrd, origin)
            # Doesn't seem to be a all_sky2pix
            #pix = self.wcs.all_sky2pix(skycrd, origin)
            # astropy only?
            pix = self.wcs.wcs_world2pix(skycrd, origin)

        except Exception, e:
            print ("Error calculating radectopix: %s" % (str(e)))
            raise WCSError(e)

        x = float(pix[0, 0])
        y = float(pix[0, 1])
        return (x, y)

    def pixtocoords(self, idxs, system=None, coords='data'):

        if self.coordsys == 'raw':
            raise WCSError("No usable WCS")

        if system == None:
            system = 'icrs'
            
        # Get a coordinates object based on ra/dec wcs transform
        ra_deg, dec_deg = self.pixtoradec(idxs, coords=coords)
        self.logger.debug("ra, dec = %f, %f" % (ra_deg, dec_deg))
        
        # convert to astropy coord
        try:
            fromclass = self.coord_table[self.coordsys]
        except KeyError:
            raise WCSError("No such coordinate system available: '%s'" % (
                self.coordsys))
            
        coord = fromclass(ra_deg, dec_deg,
                          unit=(units.degree, units.degree))

        if (system == None) or (system == self.coordsys):
            return coord
            
        # Now give it back to the user in the system requested
        try:
            toclass = self.coord_table[system]
        except KeyError:
            raise WCSError("No such coordinate system available: '%s'" % (
                system))

        coord = coord.transform_to(toclass)
        return coord

    def _deg(self, coord):
        # AstroPy changed the API so now we have to support more 
        # than one--we don't know what version the user has installed!
        if hasattr(coord, 'degrees'):
            return coord.degrees
        else:
            return coord.degree
        
    def pixtosystem(self, idxs, system=None, coords='data'):
        c = self.pixtocoords(idxs, system=system, coords=coords)
       
        return (self._deg(c.lonangle), self._deg(c.latangle))


class AstLibWCS(BaseWCS):
    """A WCS interface for astLib.astWCS.WCS
    You need to install python module 'astLib'

        http://sourceforge.net/projects/astlib

    if you want to use this version.
    """

    def __init__(self, logger):
        super(AstLibWCS, self).__init__()

        if not have_astlib:
            raise WCSError("Please install package 'astLib' first!")
        self.logger = logger
        self.header = None
        self.wcs = None
        self.coordsys = 'raw'
        self.kind = 'astlib/wcstools'

    def load_header(self, header, fobj=None):
        self.header = {}
        # Seems pyfits header objects are not perfectly duck-typed as dicts
        #self.header.update(header)
        for key, value in header.items():
            self.header[key] = value

        self.fix_bad_headers()
        
        try:
            self.wcs = astWCS.WCS(self.header, mode='pyfits')

            self.coordsys = self.choose_coord_system(self.header)
        except Exception, e:
            self.logger.error("Error making WCS object: %s" % (str(e)))
            self.wcs = None

    def choose_coord_system(self, header):
        """Return an appropriate key code for the axes coordinate system by
        examining the FITS header.
        """
        try:
            ctype = header['CTYPE1'].strip().upper()
        except KeyError:
            return 'raw'
            #raise WCSError("Cannot determine appropriate coordinate system from FITS header")

        match = re.match(r'^GLON\-.*$', ctype)
        if match:
            return 'galactic'

        # match = re.match(r'^ELON\-.*$', ctype)
        # if match:
        #     return 'ecliptic'

        match = re.match(r'^RA\-\-\-.*$', ctype)
        if match:
            hdkey = 'RADECSYS'
            try:
                radecsys = header[hdkey]

            except KeyError:
                try:
                    hdkey = 'RADESYS'
                    radecsys = header[hdkey]
                except KeyError:
                    # missing keyword
                    # RADESYS defaults to IRCS unless EQUINOX is given
                    # alone, in which case it defaults to FK4 prior to 1984
                    # and FK5 after 1984.
                    try:
                        equinox = header['EQUINOX']
                        radecsys = 'FK5'
                    except KeyError:
                        radecsys = 'ICRS'

            radecsys = radecsys.strip().upper()
            if radecsys in ('FK4', ):
                return 'b1950'
            return 'j2000'

        #raise WCSError("Cannot determine appropriate coordinate system from FITS header")
        return 'j2000'

    def pixtoradec(self, idxs, coords='data'):
        if coords == 'fits':
            # Via astWCS.NUMPY_MODE, we've forced pixels referenced from 0
            idxs = tuple(map(lambda x: x-1, idxs))

        try:
            ra_deg, dec_deg = self.wcs.pix2wcs(idxs[0], idxs[1])
            
        except Exception, e:
            self.logger.error("Error calculating pixtoradec: %s" % (str(e)))
            raise WCSError(e)
        
        return ra_deg, dec_deg
    
    def radectopix(self, ra_deg, dec_deg, coords='data', naxispath=None):
        try:
            x, y = self.wcs.wcs2pix(ra_deg, dec_deg)

        except Exception, e:
            print ("Error calculating radectopix: %s" % (str(e)))
            raise WCSError(e)

        if coords == 'fits':
            # Via astWCS.NUMPY_MODE, we've forced pixels referenced from 0
            x, y = x+1, y+1

        return (x, y)

    def pixtosystem(self, idxs, system=None, coords='data'):

        if self.coordsys == 'raw':
            raise WCSError("No usable WCS")

        if system == None:
            system = 'j2000'
            
        # Get a coordinates object based on ra/dec wcs transform
        ra_deg, dec_deg = self.pixtoradec(idxs, coords=coords)
        self.logger.debug("ra, dec = %f, %f" % (ra_deg, dec_deg))
        
        # convert to alternate coord
        try:
            fromsys = self.coordsys.upper()

            tosys = system.upper()
            if fromsys == 'B1950':
                equinox = 1950.0
            else:
                equinox = 2000.0

            lon_deg, lat_deg = astCoords.convertCoords(fromsys, tosys,
                                                       ra_deg, dec_deg,
                                                       equinox)
        except Exception as e:
            raise WCSError("Error converting between coordinate systems '%s' and '%s': %s" % (
                fromsys, tosys, str(e)))
            
        return (lon_deg, lat_deg)


class KapteynWCS(BaseWCS):
    """A WCS interface for kapteyn.wcs.Projection
    You need to install python module 'kapteyn'

        http://www.astro.rug.nl/software/kapteyn/

    if you want to use this version.
    """

    def __init__(self, logger):
        super(KapteynWCS, self).__init__()

        if not have_kapteyn:
            raise WCSError("Please install package 'kapteyn' first!")
        self.logger = logger
        self.header = None
        self.wcs = None
        self.coordsys = 'raw'
        self.kind = 'kapteyn/WCSLIB'
        self._skyout = "equatorial icrs J2000.0"

        # see: https://github.com/astropy/coordinates-benchmark/blob/master/kapteyn/convert.py
        self.conv_d = dict(fk5='fk5', fk4='fk4,J2000_OBS', icrs='icrs',
                           galactic='galactic', ecliptic='ecliptic,J2000')

    def load_header(self, header, fobj=None):
        # For kapteyn, header just needs to be duck-typed like a dict
        self.header = {}
        # Seems pyfits header objects are not perfectly duck-typed as dicts
        #self.header.update(header)
        for key, value in header.items():
            self.header[key] = value

        self.fix_bad_headers()
        
        try:
            self.wcs = kapwcs.Projection(self.header,
                                         skyout=self._skyout)

            self.coordsys = choose_coord_system(self.header)

        except Exception, e:
            self.logger.error("Error making WCS object: %s" % (str(e)))
            self.wcs = None

    def pixtoradec(self, idxs, coords='data'):
        # Kapteyn's WCS needs pixels referenced from 1
        if coords == 'data':
            idxs = tuple(map(lambda x: x+1, idxs))
        else:
            idxs = tuple(idxs)
        #print "indexes=%s" % (str(idxs))
            
        try:
            res = self.wcs.toworld(idxs)
            ra_deg, dec_deg = res[0], res[1]
            
        except Exception, e:
            self.logger.error("Error calculating pixtoradec: %s" % (str(e)))
            raise WCSError(e)
        
        return ra_deg, dec_deg
    
    def radectopix(self, ra_deg, dec_deg, coords='data', naxispath=None):
        args = [ra_deg, dec_deg]
        if naxispath:
            args += [0] * len(naxispath)
        args = tuple(args)

        try:
            pix = self.wcs.topixel(args)

        except Exception, e:
            print ("Error calculating radectopix: %s" % (str(e)))
            raise WCSError(e)

        if coords == 'data':
            # Kapteyn's WCS returns pixels referenced from 1
            pix = map(lambda x: x-1, pix)
            
        x, y = pix[0], pix[1]
        return (x, y)

    def pixtosystem(self, idxs, system=None, coords='data'):

        if self.coordsys == 'raw':
            raise WCSError("No usable WCS")

        if system == None:
            system = 'icrs'
            
        # Get a coordinates object based on ra/dec wcs transform
        ra_deg, dec_deg = self.pixtoradec(idxs, coords=coords)
        self.logger.debug("ra, dec = %f, %f" % (ra_deg, dec_deg))
        
        # convert to alternate coord
        spec = self.conv_d[system]
        tran = kapwcs.Transformation(self._skyout, spec)
        lon_deg, lat_deg = tran((ra_deg, dec_deg))

        return lon_deg, lat_deg


class StarlinkWCS(BaseWCS):
    """A WCS interface for Starlink
    You need to install python module 'starlink-pyast'

        http://www.astro.rug.nl/software/kapteyn/

    if you want to use this version.
    """

    def __init__(self, logger):
        super(StarlinkWCS, self).__init__()

        if not have_starlink:
            raise WCSError("Please install package 'starlink-pyast' first!")
        self.logger = logger
        self.header = None
        self.wcs = None
        self.coordsys = 'raw'
        self.kind = 'starlink'

    def load_header(self, header, fobj=None):
        # For starlink, header is pulled in via pyfits adapter
        ## hdu = pyfits.PrimaryHDU()
        ## self.header = hdu.header
        ## for key, value in header.items():
        ##     self.header[key] = value
        self.header = {}
        # Seems pyfits header objects are not perfectly duck-typed
        # as dicts so we can't use update()
        for key, value in header.items():
            self.header[key] = value

        self.fix_bad_headers()

        source = []
        for key, value in header.items():
            source.append("%-8.8s= %-70.70s" % (key, repr(value)))

        # following https://gist.github.com/dsberry/4171277 to get a
        # usable WCS in Ast

        try:
            # read in the header and create the default WCS transform
            #adapter = Atl.PyFITSAdapter(hdu)
            #fitschan = Ast.FitsChan(adapter)
            fitschan = Ast.FitsChan(source)
            self.wcs = fitschan.read()
            # self.wcs is a FrameSet, with a Mapping
            #self.wcs.Report = True

            self.coordsys = choose_coord_system(self.header)

            # define a transform from this destination frame to icrs/j2000
            refframe = self.wcs.getframe(2)
            toframe = Ast.SkyFrame("System=ICRS, Equinox=J2000")
            self.icrs_trans = refframe.convert(toframe)

        except Exception, e:
            self.logger.error("Error making WCS object: %s" % (str(e)))
            self.wcs = None

    def pixtoradec(self, idxs, coords='data'):
        # Starlink's WCS needs pixels referenced from 1
        if coords == 'data':
            idxs = numpy.array(map(lambda x: x+1, idxs))
        else:
            idxs = numpy.array(idxs)
            
        try:
            # pixel to sky coords (in the WCS specified transform)
            xs, ys = [idxs[0]], [idxs[1]]
            res = self.wcs.tran([ xs, ys ], 1)
            ra_rad, dec_rad = res[0][0], res[1][0]

            # whatever sky coords to icrs coords
            res = self.icrs_trans.tran([[ra_rad], [dec_rad]], 1)
            ra_rad, dec_rad = res[0][0], res[1][0]
            ra_deg, dec_deg = math.degrees(ra_rad), math.degrees(dec_rad)
            #print ra_deg, dec_deg
            
        except Exception, e:
            self.logger.error("Error calculating pixtoradec: %s" % (str(e)))
            raise WCSError(e)
        
        return ra_deg, dec_deg
    
    def radectopix(self, ra_deg, dec_deg, coords='data', naxispath=None):
        try:
            # sky coords to pixel (in the WCS specified transform)
            ra_rad, dec_rad = math.radians(ra_deg), math.radians(dec_deg)
            xs, ys = [ra_rad], [dec_rad]
            # 0 as second arg -> inverse transform
            res = self.wcs.tran([ xs, ys ], 0)
            x, y = res[0][0], res[1][0]

        except Exception, e:
            print ("Error calculating radectopix: %s" % (str(e)))
            raise WCSError(e)

        if coords == 'data':
            # Starlink's WCS returns pixels referenced from 1
            x, y = x-1, y-1

        return (x, y)

    def pixtosystem(self, idxs, system=None, coords='data'):

        if self.coordsys == 'raw':
            raise WCSError("No usable WCS")

        if system == None:
            system = 'icrs'
            
        # define a transform from reference (icrs/j2000) to user's end choice
        refframe = self.icrs_trans.getframe(2)
        toframe = Ast.SkyFrame("System=%s, Epoch=2000.0" % (system.upper()))
        end_trans = refframe.convert(toframe)

        # Get a coordinates object based on ra/dec wcs transform
        ra_deg, dec_deg = self.pixtoradec(idxs, coords=coords)
        self.logger.debug("ra, dec = %f, %f" % (ra_deg, dec_deg))
        
        # convert to alternate coord
        ra_rad, dec_rad = math.radians(ra_deg), math.radians(dec_deg)
        res = end_trans.tran([[ra_rad], [dec_rad]], 1)
        lon_rad, lat_rad = res[0][0], res[1][0]
        lon_deg, lat_deg = math.degrees(lon_rad), math.degrees(lat_rad)

        return lon_deg, lat_deg


class BareBonesWCS(BaseWCS):
    """A very basic WCS.  Assumes J2000, units in degrees, projection TAN.

    ***** NOTE *****:
    We strongly recommend that you install one of the 3rd party python
    WCS modules referred to at the top of this module, all of which are
    much more capable than BareBonesWCS.
    ****************
    """

    def __init__(self, logger):
        super(BareBonesWCS, self).__init__()
        self.logger = logger
        self.header = {}
        self.coordsys = 'raw'
        self.kind = 'barebones'

    def load_header(self, header, fobj=None):
        self.header = {}
        for key, value in header.items():
            self.header[key] = value

        self.fix_bad_headers()
        self.coordsys = choose_coord_system(self.header)

    # WCS calculations
    def get_reference_pixel(self):
        x = float(self.get_keyword('CRPIX1'))
        y = float(self.get_keyword('CRPIX2'))
        return x, y

    def get_physical_reference_pixel(self):
        xv = float(self.get_keyword('CRVAL1'))
        yv = float(self.get_keyword('CRVAL2'))
        assert 0.0 <= xv < 360.0, \
               WCSError("CRVAL1 out of range: %f" % (xv))
        
        assert -90.0 <= yv <= 90.0, \
               WCSError("CRVAL2 out of range: %f" % (yv))
        return xv, yv

    def get_pixel_coordinates(self):
        try:
            cd11 = float(self.get_keyword('CD1_1'))
            cd12 = float(self.get_keyword('CD1_2'))
            cd21 = float(self.get_keyword('CD2_1'))
            cd22 = float(self.get_keyword('CD2_2'))

        except Exception as e:
            cdelt1 = float(self.get_keyword('CDELT1'))
            cdelt2 = float(self.get_keyword('CDELT2'))
            try:
                cd11 = float(self.get_keyword('PC1_1')) * cdelt1
                cd12 = float(self.get_keyword('PC1_2')) * cdelt1
                cd21 = float(self.get_keyword('PC2_1')) * cdelt2
                cd22 = float(self.get_keyword('PC2_2')) * cdelt2
            except KeyError:
                cd11 = float(self.get_keyword('PC001001')) * cdelt1
                cd12 = float(self.get_keyword('PC001002')) * cdelt1
                cd21 = float(self.get_keyword('PC002001')) * cdelt2
                cd22 = float(self.get_keyword('PC002002')) * cdelt2

        return (cd11, cd12, cd21, cd22)

    def pixtoradec(self, idxs, coords='data'):
        """Convert a (x, y) pixel coordinate on the image to a (ra, dec)
        coordinate in space.

        Parameter (coords):
        - if 'data' then x, y coordinates are interpreted as 0-based
        - otherwise coordinates are interpreted as 1-based (traditional FITS)
        """
        x, y = idxs[:2]
        
        # account for DATA->FITS coordinate space
        if coords == 'data':
            x, y = x + 1, y + 1

        crpix1, crpix2 = self.get_reference_pixel()
        crval1, crval2 = self.get_physical_reference_pixel()
        cd11, cd12, cd21, cd22 = self.get_pixel_coordinates()

        ra_deg = (cd11 * (x - crpix1) + cd12 * 
                 (y - crpix2)) / math.cos(math.radians(crval2)) + crval1
        dec_deg = cd21 * (x - crpix1) + cd22 * (y - crpix2) + crval2

        return ra_deg, dec_deg
   
    def radectopix(self, ra_deg, dec_deg, coords='data', naxispath=None):
        """Convert a (ra_deg, dec_deg) space coordinates to (x, y) pixel
        coordinates on the image.  ra and dec are expected as floats in
        degrees.

        Parameter (coords):
        - if 'data' then x, y coordinates are returned as 0-based
        - otherwise coordinates are returned as 1-based (traditional FITS)
        """
        crpix1, crpix2 = self.get_reference_pixel()
        crval1, crval2 = self.get_physical_reference_pixel()
        cd11, cd12, cd21, cd22 = self.get_pixel_coordinates()

        # reverse matrix
        rmatrix = (cd11 * cd22) - (cd12 * cd21)

        if not cmp(rmatrix, 0.0):
            raise WCSError("WCS Matrix Error: check values")

        # Adjust RA as necessary
        if (ra_deg - crval1) > 180.0:
            ra_deg -= 360.0
        elif (ra_deg - crval1) < -180.0:
            ra_deg += 360.0

        try:
            x = (cd22 * math.cos(crval2 * math.pi/180.0) *
                 (ra_deg - crval1) - cd12 *
                 (dec_deg - crval2))/rmatrix + crpix1
            y = (cd11 * (dec_deg - crval2) - cd21 *
                 math.cos(crval2 * math.pi/180.0) *
                 (ra_deg - crval1))/rmatrix + crpix2

        except Exception, e:
            raise WCSError("radectopix calculation error: %s" % str(e))

        # account for FITS->DATA space
        if coords == 'data':
            x, y = x - 1, y - 1
        return (x, y)

    def pixtocoords(self, idxs, system='icrs', coords='data'):
        return None
    

class WcslibWCS(AstropyWCS):
    """DO NOT USE--this class name to be deprecated."""
    pass


################## Help functions ##################

def choose_coord_units(header):
    """Return the appropriate key code for the units value for the axes by
    examining the FITS header.
    """
    cunit = header['CUNIT1']
    match = re.match(r'^deg\s*$', cunit)
    if match:
        return 'degree'

    #raise WCSError("Don't understand units '%s'" % (cunit))
    return 'degree'
    

def choose_coord_system(header):
    """Return an appropriate key code for the axes coordinate system by
    examining the FITS header.
    """
    try:
        ctype = header['CTYPE1'].strip().upper()
    except KeyError:
        return 'raw'
        #raise WCSError("Cannot determine appropriate coordinate system from FITS header")
    
    match = re.match(r'^GLON\-.*$', ctype)
    if match:
        return 'galactic'

    match = re.match(r'^ELON\-.*$', ctype)
    if match:
        return 'ecliptic'

    match = re.match(r'^RA\-\-\-.*$', ctype)
    if match:
        hdkey = 'RADECSYS'
        try:
            radecsys = header[hdkey]
            
        except KeyError:
            try:
                hdkey = 'RADESYS'
                radecsys = header[hdkey]
            except KeyError:
                # missing keyword
                # RADESYS defaults to IRCS unless EQUINOX is given
                # alone, in which case it defaults to FK4 prior to 1984
                # and FK5 after 1984.
                try:
                    # EQUINOX defaults to 2000 unless RADESYS is FK4,
                    # in which case it defaults to 1950.
                    equinox = header['EQUINOX']
                    radecsys = 'FK5'
                except KeyError:
                    radecsys = 'ICRS'

        radecsys = radecsys.strip()

        return radecsys.lower()

    #raise WCSError("Cannot determine appropriate coordinate system from FITS header")
    return 'icrs'


if not wcs_configured:
    # default
    WCS = BareBonesWCS

    # try to use them in this order
    for name in ('kapteyn', 'starlink', 'pyast', 'astropy'):
        if use(name, raise_err=False):
            break


#END
