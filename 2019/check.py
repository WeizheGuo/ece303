import sys

f1 = open(sys.argv[1], 'r')
f2 = open(sys.argv[2], 'r')

line1 = f1.readline().strip()
line2 = f2.readline().strip()

print len(line1), len(line2)
for i in range(len(line1)):
  if line1[i] != line2[i]:
     print '%d: %c, %c' % (i, line1[i], line2[i])

