.PHONY: FORCE

paper.pdf: FORCE
	./bin/latexrun paper.tex

.PHONY: clean
clean:
	./bin/latexrun --clean-all