PREFIX     ?= /usr
DESTDIR    ?=
BINDIR      = $(PREFIX)/bin
DATADIR     = $(PREFIX)/share
PKGDATADIR  = $(DATADIR)/lxde-settings
LIBEXECDIR  = $(PREFIX)/lib/lxde-settings
LOCALEDIR   = $(DATADIR)/locale
HELPER      = $(LIBEXECDIR)/lxde-settings-helper
PYTHON     ?= python3
VERSION    ?= 0.1.0
DEB         = build/ol-settings_$(VERSION)_all.deb

LINGUAS   := $(shell cat po/LINGUAS)
PY_FILES  := $(shell find lxde_settings -name '*.py' | sort)
MO_FILES  := $(foreach l,$(LINGUAS),build/locale/$(l)/LC_MESSAGES/lxde-settings.mo)

SUBST = sed -e 's|@PKGDATADIR@|$(PKGDATADIR)|g' -e 's|@LOCALEDIR@|$(LOCALEDIR)|g' -e 's|@HELPER@|$(HELPER)|g'

all: $(MO_FILES) build/lxde-settings build/org.lxde.settings.policy build/config.py

build/locale/%/LC_MESSAGES/lxde-settings.mo: po/%.po
	@mkdir -p $(dir $@)
	msgfmt --check -o $@ $<

build/lxde-settings: lxde-settings.in
	@mkdir -p build
	$(SUBST) $< > $@
	chmod 755 $@

build/org.lxde.settings.policy: data/org.lxde.settings.policy.in
	@mkdir -p build
	$(SUBST) $< > $@

build/config.py: lxde_settings/config.py
	@mkdir -p build
	$(SUBST) $< > $@

# Regenerate the translation template and merge it into the .po files.
pot:
	xgettext --language=Python --keyword=_ --keyword=N_ --from-code=UTF-8 \
		--package-name=lxde-settings --add-comments=TRANSLATORS \
		-o po/lxde-settings.pot $(PY_FILES)
	for l in $(LINGUAS); do msgmerge --update --backup=none po/$$l.po po/lxde-settings.pot; done

run: $(MO_FILES)
	$(PYTHON) -m lxde_settings

check:
	$(PYTHON) -m py_compile $(PY_FILES) helper/lxde-settings-helper
	desktop-file-validate data/lxde-settings.desktop

install: all
	install -Dm755 build/lxde-settings $(DESTDIR)$(BINDIR)/lxde-settings
	for f in $(PY_FILES); do install -Dm644 $$f $(DESTDIR)$(PKGDATADIR)/$$f; done
	install -Dm644 build/config.py $(DESTDIR)$(PKGDATADIR)/lxde_settings/config.py
	install -Dm755 helper/lxde-settings-helper $(DESTDIR)$(HELPER)
	install -Dm644 build/org.lxde.settings.policy $(DESTDIR)$(DATADIR)/polkit-1/actions/org.lxde.settings.policy
	install -Dm644 data/oslogo.png $(DESTDIR)$(PKGDATADIR)/oslogo.png
	install -Dm644 data/lxde-settings.desktop $(DESTDIR)$(DATADIR)/applications/lxde-settings.desktop
	for l in $(LINGUAS); do \
		install -Dm644 build/locale/$$l/LC_MESSAGES/lxde-settings.mo \
			$(DESTDIR)$(LOCALEDIR)/$$l/LC_MESSAGES/lxde-settings.mo; done
	$(PYTHON) -m compileall -q -d $(PKGDATADIR) $(DESTDIR)$(PKGDATADIR) || true

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/lxde-settings $(DESTDIR)$(HELPER)
	rm -rf $(DESTDIR)$(PKGDATADIR) $(DESTDIR)$(LIBEXECDIR)
	rm -f $(DESTDIR)$(DATADIR)/polkit-1/actions/org.lxde.settings.policy
	rm -f $(DESTDIR)$(DATADIR)/applications/lxde-settings.desktop
	for l in $(LINGUAS); do rm -f $(DESTDIR)$(LOCALEDIR)/$$l/LC_MESSAGES/lxde-settings.mo; done

deb: all
	rm -rf build/deb
	$(MAKE) install DESTDIR=$(CURDIR)/build/deb PREFIX=/usr
	find build/deb -name __pycache__ -type d -prune -exec rm -rf {} +
	mkdir -p build/deb/DEBIAN
	sed -e 's|@VERSION@|$(VERSION)|' -e "s|@SIZE@|$$(du -sk --exclude=DEBIAN build/deb | cut -f1)|" \
		data/control.in > build/deb/DEBIAN/control
	dpkg-deb --root-owner-group --build build/deb $(DEB)

clean:
	rm -rf build
	find lxde_settings helper -name __pycache__ -type d -exec rm -rf {} +

.PHONY: all pot run check install uninstall deb clean
