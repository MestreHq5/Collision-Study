import cv2 as cv
from functions import *
import numpy as np

img = cv.imread("Python OpenCV\Photos\park.jpg")
cv.imshow("Boston", img)

blank = np.zeros(img.shape[:2], dtype='uint8')

b, g, r = cv.split(img)

blue = cv.merge([b, blank, blank])
green = cv.merge([blank, g, blank])
red = cv.merge([blank, blank, r])

cv.imshow('Blue', blue)
cv.imshow('Green', green)
cv.imshow('Red', red)

merged_image = cv.merge([b,g,r])
# cv.imshow("Merged", merged_image)

cv.waitKey(0)
cv.destroyAllWindows()