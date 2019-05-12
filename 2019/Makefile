INPUT ?= ./file_1MB.txt
OUTPUT ?= ./output.txt


test:
	python2.7 receiver.py > $(OUTPUT) & time python2.7 sender.py < $(INPUT) &
diff:
	diff $(INPUT) $(OUTPUT)
kill:
	pkill python2.7
clean:
	rm *.log $(OUTPUT) *.pyc
