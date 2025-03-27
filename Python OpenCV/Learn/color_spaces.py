import cv2 as cv
from functions import *

img = cv.imread("Python OpenCV\Photos\park.jpg")
cv.imshow("Boston", img)

# BGR to GrayScale
gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
# cv.imshow("Boston Grey", gray)

# BGR to HSV
hsv = cv.cvtColor(img, cv.COLOR_BGR2HSV)
# cv.imshow("HSV", hsv)

# BGR to L*A*B
lab = cv.cvtColor(img, cv.COLOR_BGR2LAB)
# cv.imshow("LAB", lab)

# BGR to RGB
rgb = cv.cvtColor(img, cv.COLOR_BGR2RGB)
cv.imshow("RGB Image", rgb)

# The opposite is possible for the most of the conversions

cv.waitKey(0)
cv.destroyAllWindows()