.PHONY: FORCE

paper.pdf: FORCE
	./bin/latexrun -W no-balance paper.tex

.PHONY: clean
clean:
	./bin/latexrun --clean-all