import cv2 as cv
from functions import *

img = cv.imread("Python OpenCV\Photos\park.jpg")
#cv.imshow("Boston", img)

# Averaging
average = cv.blur(img, (3,3))
cv.imshow("Average Blur", average)

# Gaussian Blur
gauss = cv.GaussianBlur(img, (3,3), 0)
cv.imshow("Gaussian Blur", gauss)

# Median Blur
median = cv.medianBlur(img, 3, )
cv.imshow("Medium Bllur", median) 

# Bilateral Blur
bilateral = cv.bilateralFilter(img, 10, 35, 25)
cv.imshow("Bilateral Blur", bilateral )

cv.waitKey(0)
cv.destroyAllWindows()