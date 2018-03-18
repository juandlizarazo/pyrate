#!/usr/bin/env/python
"""
Pyrate - Optical raytracing based on Python

Copyright (C) 2014-2018
               by     Moritz Esslinger moritz.esslinger@web.de
               and    Johannes Hartung j.hartung@gmx.net
               and    Uwe Lippmann  uwe.lippmann@web.de
               and    Thomas Heinze t.heinze@uni-jena.de
               and    others

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
"""

from localcoordinatestreebase import LocalCoordinatesTreeBase
from ray import RayPath, RayBundle
from globalconstants import numerical_tolerance

from copy import deepcopy

import numpy as np


class OpticalElement(LocalCoordinatesTreeBase):
    """
    Represents an optical element (volume with surface boundary and inner
    surfaces representing material boundaries)
    
    :param lc (Local Coordinates of optical element)
    :param name (string), if empty -> uuid
    """
    def __init__(self, lc, **kwargs):
        super(OpticalElement, self).__init__(lc, **kwargs)
        self.__surfaces = {} # Append surfaces objects
        self.__materials = {} # Append materials objects
        self.__surf_mat_connection = {} # dict["surfname"] = ("mat_minus_normal", "mat_plus_normal")
    
    
    def addSurface(self, key, surface_object, materialkeys, name=""):
        """
        Adds surface class object to the optical element.
        
        :param key (string ... dict key)
        :param surface_object (Surface class object)
        :param materialkeys (tuple of 2 strings)
                            materials in minus normal and in plus normal direction.
                            Both tuple entries must be in the optical element materials dict
        :param name (string, optional), name of surface
        """
        (minusNmat_key, plusNmat_key) = materialkeys
        if self.checkForRootConnection(surface_object.rootcoordinatesystem):
            self.__surfaces[key] = surface_object
        else:
            raise Exception("surface coordinate system should be connected to OpticalElement root coordinate system")
        self.__surfaces[key].name = name
        self.__surf_mat_connection[key] = (minusNmat_key, plusNmat_key)

    def getSurfaces(self):
        return self.__surfaces
        
    surfaces = property(fget=getSurfaces)
        

    def addMaterial(self, key, material_object, comment=""):
        """
        Adds material class object to the optical element.

        :param key (string ... dict key)
        :param material_object (Material class object)
        :param comment (string, optional), comment for the material
        """
        if self.checkForRootConnection(material_object.lc):
            if key not in self.__materials:
                self.__materials[key] = material_object
                self.__materials[key].comment = comment
            else:
                self.warning("Material key " + str(key) + " already taken. Material will not be added.")
        else:
            raise Exception("material coordinate system should be connected to OpticalElement root coordinate system")            

    def findoutWhichMaterial(self, mat1, mat2, current_mat):
        """
        Dirty method to determine material after refraction. 
        (Reference comparison.)
        
        :param mat1 (Material object)
        :param mat2 (Material object)
        :param current_mat (Material object)
        
        :return (Material object)
        """        
        
        if id(mat1) == id(current_mat):
            returnmat = mat2
        else:
            returnmat = mat1
            
        return returnmat

    def sequence_to_hitlist(self, seq):
        """
        Converts surface sequence of optical element into hitlist which is
        necessary to distinguish between multiple crossings of the pilot ray
        between surface boundaries, due to the changed transfer matrices.
        """
        
        surfnames = [(name, options_dict) for (name, options_dict) in seq]
    
        hitlist_dict = {}
        
        hitlist = []
        optionshitlistdict = {}
        
        for ((sb, optsb), (se, optse)) in zip(surfnames[:-1], surfnames[1:]):
            
            hit = hitlist_dict.get((sb, se), 0)
            hit += 1
            hitlist_dict[(sb, se)] = hit
            
            hitlist.append((sb, se, hit))
            optionshitlistdict[(sb, se, hit)] = (optsb, optse)
        
        return (hitlist, optionshitlistdict)
        
    def hitlist_to_sequence(self, (hitlist, optionshitlistdict)):
        seq = []
        
        for (ind, (sb, se, hit)) in enumerate(hitlist):
            pair = (sb, True, optionshitlistdict[(sb, se, hit)][0])
            seq.append(pair)
            if ind == len(hitlist) - 1:
                pair = (se, True, optionshitlistdict[(sb, se, hit)][1])
                seq.append(pair)
        return seq

    def calculateXYUV(self, pilotinitbundle, sequence, background_medium, pilotraypath_nr=0, use6x6=True):

        # TODO: needs heavy testing        
        
        def reduce_matrix_x(m):
            """
            Pilot ray is at position 0 (hail to the chief ray) in the pilot bundle.
            We first subtract the pilot ray and afterwards take the first two lines (x, y) from
            the components without pilot ray.
            """
            return np.array((m - m[:, 0].reshape((3, 1)))[0:2, 1:])

        def reduce_matrix_k(m):
            return reduce_matrix_x(m)
        
        def reduce_matrix_k_real(m):        
            """
            Pilot ray is at position 0 (hail to the chief ray) in the pilot bundle.
            We first subtract the pilot ray and afterwards take the first two lines (x, y) from
            the components without pilot ray.
            """
            return (np.array((m - m[:, 0].reshape((3, 1)))[0:2, 1:])).real

        def reduce_matrix_k_imag(m):        
            """
            Pilot ray is at position 0 (hail to the chief ray) in the pilot bundle.
            We first subtract the pilot ray and afterwards take the first two lines (x, y) from
            the components without pilot ray.
            """
            return (np.array((m - m[:, 0].reshape((3, 1)))[0:2, 1:])).imag

        def bestfit_transfer(X, Y, use6x6=False):


            XX = np.einsum('ij, kj', X, X).T
            YX = np.einsum('ij, kj', X, Y).T

            if use6x6:
                Ximag = X[4:, :]
                Yimag = Y[4:, :]
    
                if np.linalg.norm(Ximag) < numerical_tolerance or np.linalg.norm(Yimag) < numerical_tolerance:
                    self.warning("Start or end matrix contain zero rows: setting them to unity")
                    XX[4:, 4:] = np.eye(2)
                    YX[4:, 4:] = np.eye(2)
                # TODO: this is somehow arbitrary.
                # The other possibility is to given k a slight imag component
                    # may not be complex                
                
                        
            transfer = np.dot(YX, np.linalg.inv(XX))

            if not use6x6:
                if np.linalg.norm(transfer[0:2, 0:2].imag) > numerical_tolerance:
                    self.warning("The XX transfer part contains imaginary values. please consider using use6x6=True.")

            self.debug("\n" + np.array_str(transfer, precision=5, suppress_small=True))
           
            return transfer

        
        (hitlist, optionshitlistdict) = self.sequence_to_hitlist(sequence)        
        
        pilotraypaths = self.seqtrace(pilotinitbundle, sequence, background_medium, splitup=True)
        self.info("found %d pilotraypaths" % (len(pilotraypaths,)))
        self.info("selected no %d via pilotraypath_nr parameter" % (pilotraypath_nr,))        
        # a pilotraypath may not contain an internally splitted raybundle
        pilotraypath = pilotraypaths[pilotraypath_nr]        
        
        startpilotbundle = pilotraypath.raybundles[:-1]        
        endpilotbundle = pilotraypath.raybundles[1:]

        XYUVmatrices = {}
                
               
        for (pb1, pb2, surfhit) in zip(startpilotbundle, endpilotbundle, hitlist):
            
            (s1, s2, numhit) = surfhit
            
            lcstart = self.surfaces[s1].rootcoordinatesystem
            lcend = self.surfaces[s2].rootcoordinatesystem            
            
            # intersection point before refract/reflect (local coordinates surf1)
            startx = lcstart.returnGlobalToLocalPoints(pb1.x[-1])
            startk = lcstart.returnGlobalToLocalDirections(pb1.k[-1])

            # intersection point after refract/reflect (local coordinate surf1)
            fspropx = lcstart.returnGlobalToLocalPoints(pb2.x[0])
            fspropk = lcstart.returnGlobalToLocalDirections(pb2.k[0])
            
            endx_lcstart = lcstart.returnGlobalToLocalPoints(pb2.x[-1])            
            endk_lcstart = lcstart.returnGlobalToLocalDirections(pb2.k[-1])            
            
            # intersection point before refract/reflect (local coordinates surf2)
            endx = lcend.returnGlobalToLocalPoints(pb2.x[-1])
            endk = lcend.returnGlobalToLocalDirections(pb2.k[-1])
                        
            startxred = reduce_matrix_x(startx)
            startkred = reduce_matrix_k(startk)
            startkred_real = reduce_matrix_k_real(startk)
            startkred_imag = reduce_matrix_k_imag(startk)

            fspropxred = reduce_matrix_x(fspropx)
            fspropkred = reduce_matrix_k(fspropk)
            fspropkred_real = reduce_matrix_k_real(fspropk)
            fspropkred_imag = reduce_matrix_k_imag(fspropk)

            endx_lcstart_red = reduce_matrix_x(endx_lcstart)
            endk_lcstart_red = reduce_matrix_k(endk_lcstart)
            endk_lcstart_red_real = reduce_matrix_k_real(endk_lcstart)
            endk_lcstart_red_imag = reduce_matrix_k_imag(endk_lcstart)

            endxred = reduce_matrix_x(endx)
            endkred = reduce_matrix_k(endk)
            endkred_real = reduce_matrix_k_real(endk)
            endkred_imag = reduce_matrix_k_imag(endk)

            (num_dims, num_pts) = np.shape(startx) # check shape            


            self.debug(str([s1, s2]))
            if use6x6:
                startmatrix = np.vstack((startxred, startkred_real, startkred_imag))
                fspropmatrix = np.vstack((fspropxred, fspropkred_real, fspropkred_imag))
                endmatrix_lcstart = np.vstack((endx_lcstart_red, endk_lcstart_red_real, endk_lcstart_red_imag))
                endmatrix = np.vstack((endxred, endkred_real, endkred_imag))
            else:
                startmatrix = np.vstack((startxred, startkred))
                fspropmatrix = np.vstack((fspropxred, fspropkred))
                endmatrix_lcstart = np.vstack((endx_lcstart_red, endk_lcstart_red))
                endmatrix = np.vstack((endxred, endkred))
                       

            self.debug("refraction")
            refractmatrix = bestfit_transfer(startmatrix, fspropmatrix, use6x6=use6x6)
            self.debug("propagation")                    
            propagatematrix = bestfit_transfer(fspropmatrix, endmatrix_lcstart, use6x6=use6x6)
            self.debug("coordinate trafo")                    
            coordinatetrafomatrix = bestfit_transfer(endmatrix_lcstart, endmatrix, use6x6=use6x6)
            self.debug("full transfer")                                        
            transfer = np.dot(coordinatetrafomatrix, np.dot(propagatematrix, refractmatrix)) 
            self.debug(np.array_str(transfer, precision=5, suppress_small=True))
            transfer_comparison = bestfit_transfer(startmatrix, endmatrix, use6x6=use6x6) 
            
            self.debug("condition number:")
            self.debug(np.linalg.cond(transfer))
            
            XYUVmatrices[(s1, s2, numhit)] = transfer
            XYUVmatrices[(s2, s1, numhit)] = np.linalg.inv(transfer)


        return (pilotraypath, XYUVmatrices)
     

    def seqtrace(self, raybundle, sequence, background_medium, splitup=False):
        
        # FIXME: should depend on a list of RayPath        
        
        current_material = background_medium    
    
        rpath = RayPath(raybundle)    
        rpaths = [rpath]
        
        # surfoptions is intended to be a comma separated list
        # of keyword=value pairs        
        
        for (surfkey, surfoptions) in sequence:
            
            refract_flag = not surfoptions.get("is_mirror", False)
            # old: current_bundle = rpath.raybundles[-1]            
            # old: current_material.propagate(current_bundle, current_surface)

            rpaths_new = []            

            current_surface = self.__surfaces[surfkey]
                        
            (mnmat, pnmat) = self.__surf_mat_connection[surfkey]
            mnmat = self.__materials.get(mnmat, background_medium)
            pnmat = self.__materials.get(pnmat, background_medium)

            # finalize current_bundles
            for rp in rpaths:
                current_bundle = rp.raybundles[-1]
                current_material.propagate(current_bundle, current_surface)
                
                        
            # TODO: remove code doubling
            if refract_flag:
                # old: current_material = self.findoutWhichMaterial(mnmat, pnmat, current_material)
                # old: rpath.appendRayBundle(current_material.refract(current_bundle, current_surface))
                # old: finish

                current_material = self.findoutWhichMaterial(mnmat, pnmat, current_material)

                for rp in rpaths:
                    current_bundle = rp.raybundles[-1]
                    raybundles = current_material.refract(current_bundle, current_surface, splitup=splitup)
                                            
                    for rb in raybundles[1:]: # if there are more than one return value, copy path
                        rpathprime = deepcopy(rp)
                        rpathprime.appendRayBundle(rb)
                        rpaths_new.append(rpathprime)
                    rp.appendRayBundle(raybundles[0])


            else:
                # old: rpath.appendRayBundle(current_material.reflect(current_bundle, current_surface))
                # old: finish
            
                for rp in rpaths:
                    current_bundle = rp.raybundles[-1]
                    raybundles = current_material.reflect(current_bundle, current_surface, splitup=splitup)
    
                    for rb in raybundles[1:]:
                       rpathprime = deepcopy(rp)
                       rpathprime.appendRayBundle(rb)
                       rpaths_new.append(rpathprime)
                    rp.appendRayBundle(raybundles[0])
            
            rpaths = rpaths + rpaths_new
            
        return rpaths
        
    
    def para_seqtrace(self, pilotbundle, raybundle, sequence, background_medium, pilotraypath_nr=0, use6x6=True):
        
        rpath = RayPath(raybundle)
        (pilotraypath, matrices) = self.calculateXYUV(pilotbundle, sequence, background_medium, pilotraypath_nr=pilotraypath_nr, use6x6=use6x6)

        (hitlist, optionshitlistdict) = self.sequence_to_hitlist(sequence)
        
        for (ps, pe, surfhit) in zip(pilotraypath.raybundles[:-1], pilotraypath.raybundles[1:], hitlist):
            (surf_start_key, surf_end_key, hit) = surfhit

            surf_start = self.__surfaces[surf_start_key]
            surf_end = self.__surfaces[surf_end_key]
            
            x0_glob = rpath.raybundles[-1].x[-1]
            k0_glob = rpath.raybundles[-1].k[-1]

            newbundle = RayBundle(x0_glob, k0_glob, None, rpath.raybundles[-1].rayID, wave=rpath.raybundles[-1].wave)

            x0 = surf_start.rootcoordinatesystem.returnGlobalToLocalPoints(x0_glob)
            k0 = surf_start.rootcoordinatesystem.returnGlobalToLocalDirections(k0_glob)
            
            px0 = surf_start.rootcoordinatesystem.returnGlobalToLocalPoints(ps.x[-1][:, 0].reshape((3, 1)))
            pk0 = surf_start.rootcoordinatesystem.returnGlobalToLocalDirections(ps.k[-1][:, 0].reshape((3, 1)))

            px1 = surf_end.rootcoordinatesystem.returnGlobalToLocalPoints(pe.x[-1][:, 0].reshape((3, 1)))
            pk1 = surf_end.rootcoordinatesystem.returnGlobalToLocalDirections(pe.k[-1][:, 0].reshape((3, 1)))
            
            dx0 = (x0 - px0)[0:2]
            if use6x6:
                dk0_real = (k0 - pk0)[0:2].real
                dk0_imag = (k0 - pk0)[0:2].imag
                
                DX0 = np.vstack((dx0, dk0_real, dk0_imag))
            else:
                dk0 = (k0 - pk0)[0:2]
                DX0 = np.vstack((dx0, dk0))

            DX1 = np.dot(matrices[surfhit], DX0)
            # multiplication is somewhat contra-intuitive
            # Xend = M("surf2", "surf3", 1) M("surf1", "surf2", 1) X0
                        
            dx1 = DX1[0:2]
            if use6x6:
                dk1 = DX1[2:4] + complex(0, 1)*DX1[4:6]
            else:
                dk1 = DX1[2:4]

            (num_dims, num_pts) = np.shape(dx1)            
            
            dx1 = np.vstack((dx1, np.zeros(num_pts, dtype=complex)))
            dk1 = np.vstack((dk1, np.zeros(num_pts, dtype=complex)))
            
            x1 = surf_end.rootcoordinatesystem.returnLocalToGlobalPoints(dx1 + px1)
            k1 = surf_end.rootcoordinatesystem.returnLocalToGlobalDirections(dk1 + pk1) 

            newbundle.append(x1, k1, newbundle.Efield[0], np.ones(num_pts, dtype=bool))
            
            #surf_end.intersect(newbundle)           
            
            # FIXME: leads to changes in the linearized raybundles due to modifications
            # at the surface boundaries; we have to perform the aperture check ourselves
            
            
            rpath.appendRayBundle(newbundle)

        return (pilotraypath, rpath)
        
        
    def draw2d(self, ax, color="grey", vertices=50, inyzplane=True, **kwargs):
        for surfs in self.surfaces.itervalues():
            surfs.draw2d(ax, color=color, vertices=vertices, inyzplane=inyzplane, **kwargs) 
