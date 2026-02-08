OUT_DIR := .latex.out

.PHONY: FORCE

paper.pdf: FORCE
	./bin/latexrun paper.tex

.PHONY: clean
clean:
	latexrun --clean-all