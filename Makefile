.PHONY: FORCE

paper.pdf: FORCE
	./bin/latexrun -W no-balance paper.tex

arxiv.tar.gz: paper.pdf
	rm -rf arxiv
	mkdir -p arxiv
	latexpand --empty-comments paper.tex > arxiv/paper.tex
	cp -R latex.out/paper.bbl usenix-2020-09.sty acmart.cls figures graphs arxiv/
	(cd arxiv && tar czf ../arxiv.tar.gz *)

.PHONY: clean
clean:
	./bin/latexrun --clean-all