import cv2 as cv
from functions import *

img = cv.imread("Photos/park.jpg")
cv.imshow("Boston", img)

translated_img = translate(img, 100, -100)
cv.imshow("Boston Translated", translated_img)

cv.waitKey(0)
cv.destroyAllWindows()