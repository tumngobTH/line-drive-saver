from app.mapping import Mapping


def test_resolve_name_prefers_mapping_entry():
    m = Mapping({"Cabc": {"folderName": "ProjectX", "folderId": "f1"}})
    assert m.folder_name_for("Cabc", fallback="Cabc") == "ProjectX"


def test_resolve_name_uses_fallback_when_absent():
    m = Mapping({})
    assert m.folder_name_for("Cxyz", fallback="Cxyz") == "Cxyz"


def test_folder_id_for_returns_none_when_absent():
    m = Mapping({})
    assert m.folder_id_for("Cxyz") is None


def test_set_and_get_folder():
    m = Mapping({})
    m.set_folder("Cabc", "ProjectX", "f1")
    assert m.folder_id_for("Cabc") == "f1"
    assert m.folder_name_for("Cabc", fallback="x") == "ProjectX"


def test_rename_keeps_folder_id():
    m = Mapping({"Cabc": {"folderName": "Old", "folderId": "f1"}})
    m.rename("Cabc", "New")
    assert m.folder_name_for("Cabc", fallback="x") == "New"
    assert m.folder_id_for("Cabc") == "f1"


def test_roundtrip_dict():
    data = {"Cabc": {"folderName": "P", "folderId": "f1"}}
    assert Mapping(data).to_dict() == data
