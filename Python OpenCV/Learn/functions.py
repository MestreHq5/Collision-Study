import cv2 as cv
import numpy as np


# Functions
def rescaleFrame(frame, scale= 0.75):
    # Works for Image, Video and Live Video
    width = int(frame.shape[1] * scale)
    height = int(frame.shape[0] * scale)
    
    dimensions = (width, height)
    
    return cv.resize(frame, dimensions, interpolation=cv.INTER_AREA)


def changeRes(capture, widht, height):
    # Works for Live Video 
    capture.set(3, widht)
    capture.set(4, height)
    
  
            
def translate(img, x, y):
    translation_Matrix = np.float32([[1,0,x],[0,1,y]])
    dimensions = (img.shape[1], img.shape[0])
    img_translated = cv.warpAffine(img, translation_Matrix, dimensions)
    
    return img_translated



def rotate(img, rot_angle, rot_point = None):
    
    (height, width) = img.shape[:2]
    
    if rot_point is None:
        rot_point = (width//2, height//2)
        
    rot_matrix = cv.getRotationMatrix2D(rot_point, rot_angle, scale = 1.0)
    dimensions = (width, height)
    
    img_rotated = cv.warpAffine(img, rot_matrix, dimensions)
    
    return img_rotated