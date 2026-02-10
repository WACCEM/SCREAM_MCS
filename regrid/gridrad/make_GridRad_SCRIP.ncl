;----------------------------------------------------------------------
; this script reads in a file that contains latitude, longitude, and potentially
; an array of masks for missing data points (e.g., land/ocean, land water point, etc)
; for a given horizontal grid.

; NCL basics: https://www.ncl.ucar.edu/Document/Manuals/Getting_Started/basics.shtml
; NCL is an interpreted langugage, similar to Matlab and Xarray-loaded python
; It has most of the functions provided by Xarray (e.g., coordinate subscritions,
; data models with coordinates and metadata, good support for netcdf and other file formats, etc.)
; and a lot of functions tailored for weather/climate sciences and for WRF/CESM outputs
; https://www.ncl.ucar.edu/Document/Functions/

; and notably regridding functions including those from the ESMF library
; http://www.ncl.ucar.edu/Applications/ESMF.shtml
; Koichi Sakaguchi, Koichi.Sakaguchi@pnnl.gov

; on NERSC systems, NCL is not available as a single module.
; instead, load the climate-utils module, which makes NCL Version 6.6.2 available
; then invoke the NCL command along with this script name:
; $> module load climate-utils
; $> ncl NCLtomakeSCRIP.ncl
;----------------------------------------------------------------------
load "$NCARG_ROOT/lib/ncarg/nclscripts/esmf/ESMF_regridding.ncl"


;;;; parameters to specify the input file ;;;;;
;; sourav gridname = "SCREAM"  ; I usualy gives a descrptive name for the grid
gridname = "GridRad"  ; I usualy gives a descrptive name for the grid

;file name (latlonfile) and directory path (inputdir)for the input file, which 
;contains lat, lon, and optionally masking arrays
inputdir ="/global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess2/maps"  
;; latlonfile = "output.scream.Cess.hourly2DVars.INSTANT.nhours_x1.2019-08-01-00000.nc"
latlonfile = "GridRad_latlon.nc"

; more details about the target grid    
latname =  "Latitude" ; name of the variable lat in the latlonfile
lonname =  "Longitude" ; name of the variable lon in the latlonfile

GridType   = "rectilinear" ; choose from:
;"rectilinear" 
; most common grids described by one-dimensional latitude and longitude coordinates
; https://www.ncl.ucar.edu/Document/glossary.shtml#R

;"curvilinear" ; 
; grids often used by regional models and satellites data where the coordinates are two-dimensional 
; https://www.ncl.ucar.edu/Document/glossary.shtml#CurvilinearGrid

;"unstructured"
; not a typical 2-d grids in which grd boxes are ordered following the lat and lon coordinates
; instead the grid coordinates require a list of nodes (connectivity information) 
;https://www.ncl.ucar.edu/Document/glossary.shtml#UnstructuredGrid

;see these websites for more information about different types of grids
; https://climatedataguide.ucar.edu/climate-tools/regridding-overview


;sourav isegional = False ; regional grid or not; False for global grid
;isegional = True ; regional grid or not; False for global grid

;directory path, where to save the new SCRIP file for the target grid 
tgtSCRIPdir ="/pscratch/sd/w/wcmca1/SCREAMv1-cess2/maps"

;output SCRIP file name. 
tgtSCRIPfile = ("SCRIP_" + gridname + ".nc")
 

;static missing data points?
MissingData = False           
MaskName_user = "NA" ;if True, what would be an appropriate name for the mask?
;MaskName = "landmask"

;note that for missing values changing with time, we need a different approach to regrid
; in that case I don't create static masks.
; https://nco.sourceforge.net/nco.html#index-_005fFillValue
; https://www.ncl.ucar.edu/Applications/ESMF.shtml#WeightsAndMasking

if(MissingData) then
    MaskName = MaskName_user
    tgtSCRIPfile = ("SCRIP_" + gridname + "_" + MaskName + ".nc")
else
    MaskName = default_fillvalue("string")
end if


;----------------------------------------------------------------------
;  Generate a description file (SCRIP) for the target grid.
;----------------------------------------------------------------------

print("gridname : " + gridname)

ESMFOpt                = True
ESMFOpt@ForceOverwrite = True
ESMFOpt@Overwrite       = True
ESMFOpt@PrintTimings   = True
ESMFOpt@Debug          = True

sfile = addfile((inputdir + "/" + latlonfile),"r") 
;read the input netcdf file and create a file object sfile

if(MissingData) then ; Necessary if x has STATIC missing values.
    ;change the output file name
    print("taking care of static missing masks")

    tgtSCRIPfile = ("SCRIP_" + tgtres + "_" + MaskName + ".nc")
    
    ;an example for for ERA5 land-sea mask
    if(gridname .eq. "ERA5_0.25deg") then
        ;read an example variable with missing values 
        svar  = rm_single_dims(sfile->LSM(0,:,:))  ; do not include time or vertical dimensions
        
        if(MaskName .eq. "ocnmask") then
            itemp = svar ; oceanmask
        else
            itemp = where(svar .lt. 1.0, 1 , 0) 
            copy_VarCoords(svar,itemp)  ;landmask
        end if
        
    end if
    
    
    ESMFOpt@GridMask  = itemp     
    
end if
;warning:NetOpenFile: MissingToFillValue option set True, but missing_value attribute and data variable (evapr) types differ: not adding virtual _FillValue attribute
; read in the latitude and longitude arrays 
ilat = sfile->$latname$
ilon = sfile->$lonname$

sdims = dimsizes(ilat)
ndims = dimsizes(sdims)

; need to remove any unecessary dimensions
; such as time in the WRF output
; assuming such additional dimensions has a size of 1

if(GridType .eq. "curvilinear") 
    if (ndims .gt. 2) then
        ilat := rm_single_dims(ilat) ; the ":=" operate overwrites the variable
        ilon := rm_single_dims(ilon) 
    end if
else
    if(ndims .gt. 1) then
        ilat := rm_single_dims(ilat) 
        ilon := rm_single_dims(ilon) 
    end if
    
end if

print("running ESMF function")
; run the ESMF functions, defined for different types of grid
if( GridType .eq. "rectilinear") then   ; non-uniform (can be) lat&lon grid
     print("calling rectilinear_to_SCRIP")
     rectilinear_to_SCRIP((tgtSCRIPdir + "/" + tgtSCRIPfile),ilat,ilon,ESMFOpt)
     
else if( GridType .eq. "curvilinear") then  ;---If we have 2D lat/lon arrays.
     print("calling curvilinear_to_SCRIP")
     curvilinear_to_SCRIP((tgtSCRIPdir + "/" + tgtSCRIPfile),ilat,ilon,ESMFOpt)
     
else if( GridType .eq. "unstructured") then ;unstructured grids. Only SE mesh.
     unstructured_to_ESMF((tgtSCRIPdir + "/" + tgtSCRIPfile),ilat,ilon,ESMFOpt)
     end if
end if
end if

;that's it
