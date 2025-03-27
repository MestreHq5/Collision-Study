import cv2 as cv
from functions import *
import numpy as np
import matplotlib.pyplot as plt

img = cv.imread('Python OpenCV\Photos\cats.jpg')
# cv.imshow('Cats', img)

gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
# cv.imshow('Cats GrayScale', gray)

# Masks
blank = np.zeros(img.shape[:2], dtype='uint8')
mask = cv.circle(blank, (img.shape[1]//2, img.shape[0]//2), 100,  255, -1)

# Mask 1
masked_1 = cv.bitwise_and(gray, gray, mask = mask)
cv.imshow('Masked Image 1', masked_1)


# Mask 2
masked_2 = cv.bitwise_and(img, img, mask = mask)
cv.imshow('Masked Image 2', masked_2)


# Gray Scale Histogram
gray_hist = cv.calcHist([gray], [0], mask, [256], [0,256])
plt.figure()
plt.title('GrayScale Histogram')
plt.xlabel('Bins')
plt.ylabel('Number of Pixels')
plt.plot(gray_hist)
plt.xlim([0,256])
plt.show()


# Color Histogram
plt.figure()
plt.title('Color Histogram')
plt.xlabel('Bins')
plt.ylabel('Number of Pixels')
colors = ('b', 'g', 'r')

for i,col in enumerate(colors):
    color_hist = cv.calcHist([img], [i], mask, [256], [0,256])
    plt.plot(color_hist, color = col)
    plt.xlim([0,256])

plt.show()




cv.waitKey(0)
cv.destroyAllWindows()