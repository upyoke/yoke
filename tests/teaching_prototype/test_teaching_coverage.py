"""Registry drift and public installation wording remain visible to authors."""

from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / 'docs/teaching/tools'


def test_registry_coverage_requires_direct_mappings(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    from model import Model
    from model_checks import check_registry_coverage

    model = Model(concepts={
        'parent': {'commands': ['yoke group'], 'functions': ['group.read']},
        'parent/child': {},
    })
    live = dict(commands={'yoke group', 'yoke group child'},
                functions={'group.read', 'child.read'}, skills={'help'})
    check_registry_coverage(model, live)
    assert len(model.problems) == 3
    assert all(p.code == 'UNMAPPED_REGISTRY_ENTRY' for p in model.problems)
    assert all('add it to the appropriate concept' in p.message for p in model.problems)
    assert any('yoke group child' in p.message for p in model.problems)
    model.problems.clear()
    model.concepts['parent/child'] = dict(commands=['yoke group child'],
                                         functions=['child.read'], skills=['help'])
    check_registry_coverage(model, live)
    assert not model.problems


def test_public_install_changes_reach_both_cards(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(TOOLS))
    import install_source
    import render_explorer
    from model import load

    monkeypatch.setattr(install_source, 'REPO', tmp_path)
    public = tmp_path / install_source.INSTALL_DOC
    public.parent.mkdir(parents=True)
    public.write_text('# Install\n\n```bash\nnew-installer --guided\n```\n\n'
                      'The installer chooses its mode from the terminal.\n')
    model = load()
    nodes = {node['id']: node for node in render_explorer.map_nodes(model)}
    assert not model.problems
    assert 'new-installer --guided' in nodes['branch:install-command']['summary']
    assert nodes['installer:script']['form'][2] == 'new-installer --guided'
    for key in ('branch:install-command', 'installer:script'):
        assert 'chooses its mode from the terminal' in nodes[key]['summary']


def test_public_install_failure_names_recovery(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(TOOLS))
    import install_source
    from model import Model

    monkeypatch.setattr(install_source, 'REPO', tmp_path)
    model = Model()
    assert install_source.read_install(model) == ('', '')
    assert [p.code for p in model.problems] == ['GUIDE_SOURCE_UNREADABLE']
    assert 'restore the public shell recipe' in model.problems[0].message
    public = tmp_path / install_source.INSTALL_DOC
    public.parent.mkdir(parents=True)
    public.write_text('# Install\nNo recipe.\n')
    model.problems.clear()
    install_source.read_install(model)
    assert 'no shell installation recipe' in model.problems[0].message


def test_unmapped_registry_entry_stops_build_before_publication(monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(TOOLS))
    import build

    live = build.inventory.live_registries()
    live['commands']['yoke unmapped-example'] = None
    monkeypatch.setattr(build.inventory, 'live_registries', lambda: live)

    def unexpected_render(*args, **kwargs):
        raise AssertionError('incomplete registry reached rendering')

    monkeypatch.setattr(build, 'GuideData', unexpected_render)
    assert build.main(['--check']) == 1
    output = capsys.readouterr().out
    assert 'UNMAPPED_REGISTRY_ENTRY' in output
    assert 'yoke unmapped-example' in output
    assert 'add it to the appropriate concept' in output
