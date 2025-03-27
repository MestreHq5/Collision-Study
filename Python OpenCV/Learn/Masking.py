import cv2 as cv
from functions import *
import numpy as np

img = cv.imread('Python OpenCV\Photos\cats.jpg')
cv.imshow('Cats', img)

blank = np.zeros(img.shape[:2], dtype='uint8')
cv.imshow('Blank Image', blank)

mask = cv.circle(blank, (img.shape[1]//2, img.shape[2]//2), 100,  255, -1)
cv.imshow('Mask', mask)

masked_image = cv.bitwise_and(img, img, mask=mask)
cv.imshow("Masked Image", masked_image)

# Size of the mask has to be the same size of the image 
# Weird Shapes can be used as Mask

cv.waitKey(0)
cv.destroyAllWindows()