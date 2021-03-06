# -*- coding: utf-8 -*-
"""
Our solution for the project «Fluid detection in OCT»

@author: grotti, hiller, parker
"""

import glob, os, numpy, sys
import matplotlib.pyplot as plt
from PIL import Image, ImageChops
from skimage import filters
from skimage.color import rgb2gray
from skimage.draw import polygon
from skimage.measure import find_contours
from skimage.filters import threshold_yen, median, threshold_otsu
from skimage.io import imread
from skimage.feature import blob_doh, canny
from skimage.restoration import (denoise_tv_chambolle, denoise_bilateral,
                                 denoise_wavelet, estimate_sigma)
from skimage.exposure import equalize_adapthist
from skimage import util

def create_bg1_mask(image):
    #returns a mask where the outsdie is set to black and the inside (of interest) is white
    image_grey = rgb2gray(image)
    image_grey[image_grey >= 0.9] = 0
    image_grey = equalize_adapthist(image_grey)
    #equalize the histogram for under and overexposed pictures
    image_gaussian = median(image_grey)
    #use the median filter to remove noise
    for i in range(1,5):
        image_gaussian = denoise_bilateral(image_gaussian, sigma_spatial=2, multichannel=False)
        #complete multiple iterations of the bilateral filter to strengthen (outer) contours, while decreasing noise
    image_gaussian[threshold_otsu(image_gaussian) > image_gaussian] = 0
    #if pixels above threshold set to zero 
    outer_masks = find_contours(image_gaussian, 0.01)
    #finds contours in image, returns positions
    mask = numpy.zeros_like(image_grey)

    for n, contour in enumerate(outer_masks):
        if len(contour) > 1000:
            #only take longer contours for the mask
            x, y = polygon(contour[:, 0], contour[:, 1])
            mask[x, y] = 1
            #if inside fragment set to 1

    return mask

def crop_to_mask(image, mask):
    mask_pil = Image.fromarray(mask).convert('L') #convert image
    bg = Image.new(mask_pil.mode, mask_pil.size, mask_pil.getpixel((0, 0)))
    diff = ImageChops.difference(mask_pil, bg) #use the difference function to find the positions of a box around the mask
    bbox = diff.getbbox()
    image = numpy.copy(image)
    image[mask == 0] = 0
    image_pil = Image.fromarray(image)
    return numpy.array(image_pil.crop(bbox)), bbox

def last_notmask(x, mask, bbox, image_cropped):
    #finds the location of the last not masked pixels
    value = 0 
    for i in range(image_cropped.shape[0]-1, 0, -1):
       if (mask[i+bbox[1], x+bbox[0]]==1):
           return i
    return value

def first_notmask(x, mask, bbox, image_cropped):
    #finds the location of the first not masked pixels
    value = image_cropped.shape[0]
    for i in range(0, image_cropped.shape[0]):
       if (mask[i+bbox[1], x+bbox[0]]==1):
           return i
    return value

def fit_line(points):
#function used in previous exercise to fit lines through points
    m = 0
    c = 0
    
    x0,y0,x1,y1 = points[0][0], points[0][1], points[1][0], points[1][1]
    
    if x0 != x1:
        m = (y0 - y1)/(x0 - x1)
    else:
        m = (y0 - y1)/(x0 - x1 + sys.float_info.epsilon)
    
    c =  y1 - m*x1

    return m, c



def point_to_line_dist(m, c, x0, y0):
#function used in previous exercise to calculate distance of points from line
    dist = 0
    x1 = (y0 + x0/m - c)/(m + 1/m)
    y1 = m*x1 + c
    dist = ((x0 - x1)**2 + (y0 - y1)**2)**(1/2)
    return dist

def ransac(x, first_notmask_x, image_cropped):
#preforms RANSAC on first not masked pixels, if enough of these pixels are close enough to the fitted line the function will return True, else False
    mat = numpy.empty((len(x), 2))
    mat[:,0] = first_notmask_x
    mat[:, 1] = x
    edge_pts = mat

    edge_pts_xy = edge_pts[:, ::-1]
    
    ransac_iterations = 500
    ransac_threshold = 0.9
    n_samples = 2
    
    plotted = False
    ratio = 0.8
    model_m = 0
    model_c = 0
    
    # perform RANSAC iterations
    for it in range(ransac_iterations):
    
        all_indices = numpy.arange(edge_pts.shape[0])
        numpy.random.shuffle(all_indices)
    
        indices_1 = all_indices[:n_samples]
        indices_2 = all_indices[n_samples:]
    
        maybe_points = edge_pts_xy[indices_1, :]
        test_points = edge_pts_xy[indices_2, :]
    
        # find a line model for these points
        m, c = fit_line(maybe_points)
        num = 0
    
        # find distance to the model for all testing points
        for ind in range(test_points.shape[0]):
    
            x0 = test_points[ind, 0]
            y0 = test_points[ind, 1]
    
            # distance from point to the model
            dist = point_to_line_dist(m, c, x0, y0)
    
            # check whether it's an inlier or not
            if dist < ransac_threshold:
                num += 1
    
        # in case a new model is better - cache it
        if num / float(n_samples) > ratio:
            ratio = num / float(n_samples)
            model_m = m 
            model_c = c
    num =0
    x_new = x
    y = model_m * x_new + model_c
    for i in range(image_cropped.shape[1]):
        if -10 <(y[i] - first_notmask_x[i])<12:
            num += 1

    if num/ image_cropped.shape[1] > 0.65:
        #check if enough points close to line
        plotted = True
    return plotted

def is_dark(image_cropped, x,y):
    #returns True if area around center of blob is on average close enough to 0
    shape = image_cropped.shape
    x = int(x)
    y = int(y)
    return numpy.mean(image_cropped[max(0, y-2):min(shape[0], y+2), max(0, x-2):min(shape[1], x+2)]) < 0.2

    

def srf_detector(image):
    if_detected = False
    mask = create_bg1_mask(image)
    image_cropped_1, bbox = crop_to_mask(image, mask)
    image_cropped = rgb2gray(image_cropped_1)
    image_cropped = denoise_bilateral(image_cropped, sigma_spatial=2, multichannel=False)
    image_cropped = equalize_adapthist(image_cropped)

    x = numpy.arange(image_cropped.shape[1])
    first_notmask_x = [first_notmask(i, mask, bbox, image_cropped) for i in x]
    plotted = ransac(x, first_notmask_x, image_cropped)
    
    if plotted:
        result = 'No SRF detected'
        fig, ax = plt.subplots(1, 1, figsize=(9, 3), sharex=True, sharey=True)
        ax.set_title('Cropped Image')
        ax.imshow(image_cropped, cmap=plt.cm.gray, interpolation='nearest') 

    if plotted == False: 
        #only if no line can be fitted will the function try to find blobs
        x_tot, y_tot = image_cropped.shape[0], image_cropped.shape[1]
    
        blobs_doh = blob_doh(image_cropped, max_sigma=50, threshold=.0045)
    
        plt.rcParams['image.cmap'] = 'gray'
        result = 'No SRF detected'
        fig, ax = plt.subplots(1, 1, figsize=(9, 3), sharex=True, sharey=True)
        for blob in blobs_doh:
            ax.set_title('Detected SRF in red')
            ax.imshow(image_cropped, cmap=plt.cm.gray, interpolation='nearest')
            y, x, r = blob
            c = plt.Circle((x, y), r, color='blue', linewidth=2, fill=False)
            ax.add_patch(c)
            p = True
            f_x = first_notmask(int(x), mask, bbox, image_cropped)
            if (r >1) and (r <20) and (x > 30) and (x < y_tot-30) and (y > 50) and (y < x_tot -50) and is_dark(image_cropped,x, y) and (y > f_x + (1/4)*(image_cropped.shape[0]-x)):
                for i in range(-int(r)-3, int(r)+1+3):
                    for j in range(-int(r)-3, int(r)+1+3):
                        if (mask[int(y)+bbox[1]+i, int(x)+bbox[0]+j]==0):
                           p = False
                if p:
                    c = plt.Circle((x, y), r, color='red', linewidth=2, fill=False)
                    ax.add_patch(c)
                    result = 'SRF detected'
                    if_detected = True
    print(result)
    plt.show()
    return if_detected

results = numpy.empty(())
#images = glob.glob(os.path.join('./Train-Data/NoSRF', '*.png'))
images = glob.glob(os.path.join('./handout', '*.png'))
results = numpy.empty((len(images), 2), dtype=object)
i=0
for path in images:
    image = imread(path)
    value = srf_detector(image)
    number = 0
    if value==True:
        number = 1  
    results[i,:] = (os.path.basename(path), number)
    i +=1 

numpy.savetxt('results_Grotti_Hiller_Parker.csv', results, fmt="%s,%i", delimiter=",")
