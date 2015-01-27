"""

Function which can be useful when setting quantities

"""
import copy
import os
import anuga.utilities.spatialInputUtil as su

def make_nearestNeighbour_quantity_function(
        quantity_xyValueIn, 
        domain, 
        threshold_distance = 9.0e+100, 
        background_value = 9.0e+100,
        k_nearest_neighbours = 1,
    ):
    """
    Function which makes another function, which can be used in set_quantity 

    Idea: For every point x,y in the domain, we want to set a quantity based on
          the 'nearest-neighbours' from quantity_xyValue (a 3 column array with
          x,y,quantity-value), 
          UNLESS the distance from x,y to the nearest-neighbour is >
            threshold_distance.
          In the latter case, we want to set the quantity value to
            'background_value'
            
          We need a function f(x,y) to do that. This routine makes the
          function, with the desired quantity_xyValue points, 
          threshold_distance, and background_value

    INPUTS:
        @param quantity_xyValueIn -- A 3 column array with 'x,y, Value' 
            defining the points used to set the new quantity values
        @param domain -- The ANUGA domain
        @param k_nearest_neighbors If > 1, then an inverse-distance-weighted average
               of the k nearest neighbours is used
        @param threshold_distance -- Points greater than this distance from 
            their nearest quantity_xyValue point are set to background_value
        @param background_value -- see 'threshold_distance'

    OUTPUTS: 
        A function f which can be passed to domain.set_quantity('myQuantity', f)

    """

    import scipy
    import scipy.interpolate
    import scipy.spatial

    if(len(quantity_xyValueIn.shape) > 1):
        quantity_xyValue = quantity_xyValueIn
    else:
        # Treat the single-point case
        quantity_xyValue = quantity_xyValueIn.reshape((1,3))

    # Make a function which gives us the ROW-INDEX of the nearest xy point in
    # quantity_xyValue
    #quantity_xy_interpolator = scipy.interpolate.NearestNDInterpolator(
    #    quantity_xyValue[:,0:2], 
    #    scipy.arange(len(quantity_xyValue[:,2])))

    # Make a function which returns k-nearest-neighbour indices + distances
    quantity_xy_interpolator = scipy.spatial.cKDTree(quantity_xyValue[:,0:2])

    # Make a function of x,y which we can pass to domain.set_quantity
    def quant_NN_fun(x,y):
        """
        Function to assign quantity from the nearest point in quantity_xyValue,
        UNLESS the point is more than 'threshold_distance' away from the
        nearest point, in which case the background value is used

        """

        import scipy
        import scipy.interpolate
        import scipy.spatial

        # Since ANUGA stores x,y internally in non-georeferenced coordinates,
        # we adjust them here
        xll = domain.geo_reference.xllcorner
        yll = domain.geo_reference.yllcorner
        z = scipy.zeros(shape=(len(x), 2))
        z[:,0] = x+xll
        z[:,1] = y+yll

        # This will hold the quantity values
        quantity_output = x*0. + background_value
        # Compute the index of the nearest-neighbour in quantity_xyValue
        neighbour_data = quantity_xy_interpolator.query(z, 
            k=k_nearest_neighbours)

        # Next find indices with distance < threshold_distance
        if(k_nearest_neighbours==1):
            dist_lt_thresh = neighbour_data[0] < threshold_distance
        else:
            dist_lt_thresh = neighbour_data[0][:,0] < threshold_distance

        dist_lt_thresh = dist_lt_thresh.nonzero()[0]

        # Initialise output
        quantity_output = x*0 + background_value

        # Interpolate
        if len(dist_lt_thresh)>0:
            numerator = 0
            denominator = 0
            for i in range(k_nearest_neighbours):
                if(k_nearest_neighbours==1):
                    distances = neighbour_data[0][dist_lt_thresh]
                    indices = neighbour_data[1][dist_lt_thresh]
                else:
                    distances = neighbour_data[0][dist_lt_thresh,i]
                    indices = neighbour_data[1][dist_lt_thresh,i]
                
                inverse_distance = 1.0/(distances+1.0e-100)
                values = quantity_xyValue[indices,2]
                numerator += values*inverse_distance
                denominator += inverse_distance
           
            quantity_output[dist_lt_thresh] = numerator/denominator

        return quantity_output

    # Return the quantity function
    return quant_NN_fun

###############################################################################

def composite_quantity_setting_function(poly_fun_pairs, 
                                        domain,
                                        clip_range = None,
                                        nan_treatment = 'exception'):
    """ Make a 'composite function' to set quantities -- applies different
        functions inside different polygon regions.

        poly_fun_pairs = [ [p0, f0], [p1, f1], ...]

        Where:

          fi is a function,
             or a constant,
             or a '.txt' or '.csv' file with comma separated xyz data
                and an optional header row which contains letters,
             or the name of a gdal-compatible rasterFile
                (not ending in .txt or .csv),
             or a numpy array with 3 columns

          pi is a polygon (anuga polygon format),
            or a polygon filename (shapefile or a csv format that
                                    anuga.read_polygon will read),
            or None ( equivalent to a polygon with zero area),
            or 'All' (equivalent to a polygon covering everything)
            or 'Extent' in the case that fi is a rasterFile name
                (equivalent to a polygon with the same extent as the raster)

        IMPORTANT: When polygons overlap, the first elements of the list are
                   given priority. The approach is:
                   First f0 is applied to all points in p0, and we record
                     that these points have been 'set'
                   Next f1 is applied to all points in p1 which have not
                     been 'set', and then we record those points as being 'set'
                   Next f2 is applied to all points in p2 which have not
                     been 'set', and then we record those points as being 'set'
                   ... etc

        INPUT:
          @param poly_fun_pairs = [ [p0, f0], [p1, f1], ...]

              where fi(x,y) is a function returning quantity values at points,
                or any of the special cases below

              SPECIAL fi CASES:
              fi = a constant in which case points in the polygon are
                   set to that value, 
              fi = a .txt or .csv file name containing x, y, z data,
                     with comma separators and an optional header row 
                     containing letters
              fi = a string rasterFile name (not ending in .txt or .csv)
                    which can be passed to quantityRasterFun to make a function,
              fi = a numpy array with 3 columns (x,y,Value) in which case
                   nearest-neighbour interpolation is used on the points

              pi are polygons where we want to use fi inside 
              (anuga polygon format) or any of the special cases below
              SPECIAL pi CASES:
              If pi is a filename ending in .shp or a csv format that
                anuga.read_polygon can read, we assume it contains a polygon 
                we have to read
              If any pi = 'All', then we assume that ALL unset points are set
                 using the function. This CAN ONLY happen in the last [fi,pi] 
                 pair where pi is not None (since fi will be applied to 
                 all remaining points -- so anything else is probably an 
                 input mistake)
              If any pi = None, then that [fi,pi] pair is skipped
              If pi = 'Extent' and fi is the name of a raster file, then the
                extent of the raster file is used to define the polygon

          @param domain = ANUGA domain object

          @param clip_range = List with the same length as poly_fun_pairs, 
                 of the form:
                 [ [min0, max0], [min1, max1], ...]
                 After f0 is applied in p0, its values will be 'clipped' to the
                 range
                    [min0, max0]
                 , and similarly for the other fi

          @param nan_treatment = 'exception' or 'fall_through' -- string determining
                what to do if F(x,y) is nan. The default 'exception' raises an exception.
                The value 'fall_through' allows the function to try lower-priority 
                poly,fun pairs (in sequence) to set the value.

        OUTPUT: A function F(x,y) which can be used e.g. to set the quantity
                domain.set_quantity('elevation', F)
    """
    import os
    import numpy
    from anuga.geometry.polygon import inside_polygon

    # Check that clip_range has the right form
    if clip_range is not None:
        if len(clip_range) != len(poly_fun_pairs):
            msg = ' clip_range must be the same ' +\
                  'length as poly_fun_pairs, or None'
            raise ValueError(msg)
        # Check that min < = max
        for i in range(len(clip_range)):
            if clip_range[i][0] > clip_range[i][1]:
                raise Exception('clip_range minima must be less than maxima')

    def F(x,y):
        """This is the function we return
           It can be passed to set_quantity
        """
        isSet=numpy.zeros(len(x)) # 0/1 - record if each point has been set
        quantityVal=x*0 # Function return value
        lpf=len(poly_fun_pairs)
        if(lpf<=0):
            raise Exception('Must have at least 1 fun-poly-pair')

        # Make an array of 'transformed' spatial coordinates, for checking
        # polygon inclusion
        xll=domain.geo_reference.xllcorner
        yll=domain.geo_reference.yllcorner
        xy_array_trans=numpy.vstack([x+xll,y+yll]).transpose()

        # Check that none of the pi polygons [except perhaps the last] is 'All'
        for i in range(lpf-1):
            if(poly_fun_pairs[i][0]=='All'):
                # This is only ok if all the othe poly_fun_pairs are None
                remaining_poly_fun_pairs_are_None = \
                    [poly_fun_pairs[j][0] is None for j in range(i+1,lpf)]
                if(not all(remaining_poly_fun_pairs_are_None)):
                    raise Exception('Can only have the last polygon = All')

        # MAIN LOOP
        # Apply the fi inside the pi
        for i in range(lpf):
            fi = poly_fun_pairs[i][1] # The function
            pi = poly_fun_pairs[i][0] # The polygon

            # Quick exit
            if(pi is None):
                continue

            ###################################################################
            # Get indices fInds of points in polygon pi which are not already
            # set
            ###################################################################
            if(pi == 'All'):
                # Get all unset points
                fInside=(1-isSet)
                fInds=(fInside==1).nonzero()[0]

            else:

                if(pi == 'Extent'):
                    # Here fi MUST be a gdal-compatible raster
                    if(not (type(fi)==str)):
                        msg = ' pi = "Extent" can only be used when fi is a' +\
                              ' raster file name'
                        raise Exception(msg)

                    if(not os.path.exists(fi)):
                        msg = 'fi ' + str(fi) + ' is supposed to be a ' +\
                              ' raster filename, but it could not be found'
                        raise Exception(msg)

                    # Then we get the extent from the raster itself
                    pi_path=su.getRasterExtent(fi,asPolygon=True)

                elif(type(pi)==str and os.path.isfile(pi) ): 
                    # pi is a file
                    pi_path=su.read_polygon(pi)

                else:
                    # pi is the actual polygon data
                    pi_path=pi

                # Get the insides of unset points inside pi_path
                notSet=(isSet==0.).nonzero()[0]
                fInds = inside_polygon(xy_array_trans[notSet,:], pi_path)
                fInds = notSet[fInds]

            if len(fInds) == 0:
                # No points found, move on
                continue

            ###################################################################
            # Evaluate fi at the points inside pi
            ###################################################################

            # We use various tricks to infer whether fi is a function,
            # a constant, a file (raster or csv), or an array
            if(hasattr(fi,'__call__')):
                # fi is a function
                quantityVal[fInds] = fi(x[fInds], y[fInds])

            elif isinstance(fi, (int, long, float)):
                # fi is a numerical constant
                quantityVal[fInds]=fi*1.0

            elif ( type(fi) is str and os.path.exists(fi)):
                # fi is a file which is assumed to be 
                # a gdal-compatible raster OR an x,y,z elevation file
                if os.path.splitext(fi)[1] in ['.txt', '.csv']:
                    fi_array = su.read_csv_optional_header(fi)
                    # Check the results
                    if fi_array.shape[1] is not 3:
                        print 'Treated input file ' + fi +\
                              ' as xyz array with '+ \
                              str(int(hasLetters)) + ' header row'
                        msg = 'Array should have 3 columns -- x,y,value'
                        raise Exception(msg)

                    newfi = make_nearestNeighbour_quantity_function(
                        fi_array, domain)
                    quantityVal[fInds] = newfi(x[fInds], y[fInds])

                else:
                    # Treating input file as a raster
                    newfi = quantityRasterFun(domain, fi)
                    quantityVal[fInds] = newfi(x[fInds], y[fInds])

            elif(type(fi) is numpy.ndarray):
                if fi.shape[1] is not 3:
                    msg = 'Array should have 3 columns -- x,y,value'
                    raise Exception(msg)
                newfi = make_nearestNeighbour_quantity_function(fi, domain)
                quantityVal[fInds] = newfi(x[fInds], y[fInds])

            else:
                print 'Error with function from'
                print fi
                msg='Cannot make function from type '+str(type(fi))
                raise Exception, msg 

            ###################################################################
            # Check for nan values
            ###################################################################

            nan_flag = quantityVal[fInds] != quantityVal[fInds]
            nan_inds = nan_flag.nonzero()[0]
            if len(nan_inds)>0:
                if nan_treatment == 'exception':
                    msg = 'nan values generated by the poly_fun_pair at '\
                          'index ' + str(i) + ' '\
                          'in composite_quantity_setting_function. ' + \
                          'To allow these values to be set by later ' + \
                          'poly_fun pairs, pass the argument ' + \
                          'nan_treatment="fall_through" ' + \
                          'to composite_quantity_setting_function' 
                    raise Exception(msg)

                elif nan_treatment == 'fall_through':
                    msg = 'WARNING: nan values generated by the ' + \
                          'poly_fun_pair at index ' + str(i) + ' '\
                          'in composite_quantity_setting_function. ' + \
                          'They will be passed to later poly_fun_pairs'
                    print msg
                    not_nan_inds = (1-nan_flag).nonzero()[0]

                    if len(not_nan_inds)>0:
                        fInds = fInds[not_nan_inds]
                    else:
                        # All values are nan
                        msg = '( Actually all the values were nan - ' + \
                              'Are you sure they should be? Possible error?)'
                        print msg
                        continue
                else:
                    msg = 'Found nan values in ' + \
                          'composite_quantity_setting_function but ' + \
                          'nan_treatment is not a recognized value'
                    raise Exception(msg)

            # Record that the points have been set
            isSet[fInds]=1

            # Enforce clip_range
            if clip_range is not None:
                lower_bound = clip_range[i][0]
                upper_bound = clip_range[i][1]
                quantityVal[fInds] = numpy.maximum(
                    quantityVal[fInds], lower_bound)
                quantityVal[fInds] = numpy.minimum(
                    quantityVal[fInds], upper_bound)

        # End of loop

        if( min(isSet) != 1):
            print 'Some points were not inside any polygon, ',\
                  'or evalute to nan over all datasets'
            unset_inds = (isSet!=1).nonzero()[0]
            lui = min(5, len(unset_inds)) 
            print 'There are ', len(unset_inds), ' such points'
            print 'Here are a few:'
            for i in range(lui):
                print x[unset_inds[i]]+xll, y[unset_inds[i]]+yll
            raise Exception('It seems the input data needs to be fixed')

        return quantityVal
        # END OF FUNCTION F(x,y)

    return F

##############################################################################

def quantityRasterFun(domain, rasterFile):
    """
    Make a function whick takes x,y in ANUGA coordinates, and returns the values
    on a raster rasterFile
    
    This can be used to set a quantity, and takes care of the manual conversion from 
    ANUGA coordinates to spatial coordinates.

    INPUTS: domain = ANUGA domain
            rasterFile = Filename of the raster to extract point values from
   
    OUTPUT: Function which takes x,y in ANUGA coordinates, and outputs their
            corresponding raster values 
    """
    import scipy
    from anuga.utilities.spatialInputUtil import rasterValuesAtPoints
    def QFun(x,y):
        xll=domain.geo_reference.xllcorner
        yll=domain.geo_reference.yllcorner
        inDat=scipy.vstack([x+xll,y+yll]).transpose()
        return rasterValuesAtPoints(xy=inDat,rasterFile=rasterFile)

    return QFun

#################################################################################

def quantity_from_Pt_Pol_Data_and_Raster(Pt_Pol_Data, quantity_raster, domain):
    """
        Function to make a function F(x,y) which returns the corresponding
        values on quantity_raster, except if x,y is inside the polygon associated with
        any element of Pt_Pol_Data, in which case a Pt_Pol_-specific nearest neighbour
        interpolator is used.

        INPUT:
            Pt_Pol_Data = a list with [ [ Polygon_0, Pt_XYZ_0], 
                                        [ Polygon_1, Pt_XYZ_1], 
                                        ... ]
                    Here Polygon_i is a polygon in ANUGA format,
                    and Pt_XYZ_i is a 3 column array of x,y,Value points
            quantity_raster = A GDAL-compatible quantity raster
            domain = ANUGA domain
    """

    # Function to set quantity from raster 
    qFun1=quantityRasterFun(domain, rasterFile=quantity_raster)

    # List of function/polygon pairs defining the Pt_Pol_ quantity data
    qFunChanList=[]
    for i in range(len(Pt_Pol_Data)):
        qFunChanList.append([
             Pt_Pol_Data[i][0],
             make_nearestNeighbour_quantity_function(Pt_Pol_Data[i][1], domain) 
                              ])

    #
    qFun=composite_quantity_setting_function(qFunChanList+[['All', qFun1]], domain)

    return qFun
