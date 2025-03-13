import cv2 as cv
from functions import *
import numpy as np

# AND OR XOR NOT

blank = np.zeros((400,400), dtype = 'uint8')

rectangle = cv.rectangle(blank.copy(), (30, 30), (370,370), 255, -1)
circle = cv.circle(blank.copy(), (200,200), 200, 255, -1)

cv.imshow('Rectangle', rectangle)
cv.imshow('Circle', circle)

# bitwise AND --> Intersecting Regions
bitwise_and = cv.bitwise_and(rectangle, circle)
#cv.imshow('Bitwise AND', bitwise_and)

# bitwise OR --> Active Regions (1) of at least one of the matrices
bitwise_or = cv.bitwise_or(rectangle, circle)
#cv.imshow('Bitwise OR', bitwise_or)

# bitwise XOR --> Active Regions (1) of at most one of the matrices 
bitwise_xor = cv.bitwise_xor(rectangle, circle)
#cv.imshow('Bitwise XOR', bitwise_xor)

# bitwise NOT --> Non-Active Regions (0)
bitwise_not = cv.bitwise_not(rectangle)
cv.imshow('Bitwise NOT', bitwise_not)



cv.waitKey(0)
cv.destroyAllWindows()