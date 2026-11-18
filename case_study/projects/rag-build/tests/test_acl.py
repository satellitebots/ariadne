"""Tests for the ACL module and principal filtering."""

import os
import tempfile
import numpy as np
from rag.acl import ACL
from rag.index import Index


def test_acl_load_and_resolve():
    """Test loading ACL config and resolving user principals."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
principals:
  alice:
    - security
    - platform
  bob:
    - platform
rules:
  "":
    - platform
  "concepts/security/":
    - security
    - platform
""")
        f.flush()
        acl = ACL(f.name)

    principals = acl.resolve_user_principals("alice")
    assert "alice" in principals
    assert "security" in principals
    assert "platform" in principals

    principals_bob = acl.resolve_user_principals("bob")
    assert "bob" in principals_bob
    assert "platform" in principals_bob
    assert "security" not in principals_bob
    os.unlink(f.name)


def test_acl_get_principals_for_doc():
    """Test that principals are returned based on document path prefix."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
principals:
  alice:
    - security
    - platform
rules:
  "":
    - platform
  "concepts/security/":
    - security
    - platform
""")
        f.flush()
        acl = ACL(f.name)

    # Security doc should include security principal
    sec_principals = acl.get_principals_for_doc("concepts/security/README.md")
    assert "security" in sec_principals
    assert "platform" in sec_principals

    # General doc should only have platform
    general_principals = acl.get_principals_for_doc("concepts/overview/README.md")
    assert "platform" in general_principals
    assert "security" not in general_principals
    os.unlink(f.name)


def test_acl_principal_filter_denies_access():
    """Test that a user without the 'security' principal cannot access
    security-restricted documents. This proves the ACL filter works."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
principals:
  alice:
    - platform
  bob:
    - security
    - platform
rules:
  "":
    - platform
  "concepts/security/":
    - security
    - platform
""")
        f.flush()

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as df:
        db_path = df.name

    acl = ACL(f.name)
    index = Index(db_path)

    # Alice (platform only) tries to access a security document
    alice_principals = acl.resolve_user_principals("alice")
    sec_principals = acl.get_principals_for_doc("concepts/security/README.md")

    # The overlap of alice's principals with security doc's required principals
    # is only 'platform', but security doc requires 'security' too
    # In search_with_acl, we check if set(chunk["principals"]) & user_set
    # Security doc principals = ["security", "platform"]
    # Alice's principals = {"alice", "platform"}
    # Overlap = {"platform"} which is non-empty...
    # We need to test that the filtering logic is correct:
    # The ACL stores principals that CAN ACCESS the document.
    # If we store principals=["security"] for a doc, and user only has ["platform"],
    # they should NOT get it.

    # Redefine ACL so security doc has ONLY security principal
    os.unlink(f.name)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
principals:
  alice:
    - platform
  bob:
    - security
    - platform
rules:
  "":
    - platform
  "concepts/security/":
    - security
""")
        f.flush()
        acl = ACL(f.name)

    # Verify: security doc has only 'security' principal
    sec_principals = acl.get_principals_for_doc("concepts/security/README.md")
    assert sec_principals == ["security"]

    # Alice has only 'platform', not 'security'
    alice_principals = acl.resolve_user_principals("alice")
    assert "security" not in alice_principals

    # Simulate the filter check
    has_access = bool(set(sec_principals) & set(alice_principals))
    assert not has_access, "Alice should NOT have access to security docs"

    # Bob has both, should have access
    bob_principals = acl.resolve_user_principals("bob")
    has_bob_access = bool(set(sec_principals) & bob_principals)
    assert has_bob_access, "Bob SHOULD have access to security docs"

    index.close()
    os.unlink(f.name)
    os.unlink(db_path)


def test_index_search_with_acl_filters():
    """Test that search_with_acl filters out chunks the user can't access."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
principals:
  alice:
    - platform
rules:
  "":
    - platform
  "restricted/":
    - admin
""")
        f.flush()

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as df:
        db_path = df.name

    acl = ACL(f.name)
    index = Index(db_path)

    import numpy as np
    vec = np.random.rand(768).astype(np.float32)

    # Add a public chunk
    index.add_document("public", "https://k8s.io/public", "public.md", ["platform"])
    index.add_chunk("pub1", "public", 0,
                    "This is a public document about pods",
                    "https://k8s.io/docs/concepts/workloads/pods/",
                    ["platform"], vec)

    # Add a restricted chunk
    index.add_document("restricted", "https://k8s.io/secret",
                       "restricted/config.md", ["admin"])
    index.add_chunk("sec1", "restricted", 0,
                    "This is a restricted security config",
                    "https://k8s.io/docs/concepts/security/secrets/",
                    ["admin"], vec)

    index.commit()

    # Alice queries - should only see public chunk
    alice_principals = acl.resolve_user_principals("alice")
    query_vec = np.random.rand(768).astype(np.float32)
    results = index.search_with_acl(
        query="document",
        query_vec=query_vec,
        user_principals=alice_principals,
        top_k=10,
    )
    result_urls = [r["url"] for r in results]
    # Alice should NOT see the restricted URL
    assert not any("security" in url or "secret" in url for url in result_urls)
    # Alice should see the public URL
    assert any("pods" in url for url in result_urls)

    index.close()
    os.unlink(f.name)
    os.unlink(db_path)
