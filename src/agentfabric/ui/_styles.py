from __future__ import annotations

import streamlit as st


def apply_global_css(toolbar_mode: str | None) -> None:
    """Inject global CSS tweaks for the AgentFabric UI."""

    # Hide the top-right Deploy button while keeping the menu (three dots).
    # Streamlit's DOM changes across versions, so we include multiple selectors.
    st.markdown(
        """
<style>
  [data-testid="stDeployButton"],
  [data-testid="stToolbarDeployButton"],
  button[title="Deploy"],
  a[title="Deploy"],
  button[aria-label="Deploy"],
  a[aria-label="Deploy"] {
    display: none !important;
  }

  /* Primary button (used for connect): make it green. */
  button[kind="primary"],
  div[data-testid="baseButton-primary"] > button {
    background: #16a34a !important;
    border-color: #16a34a !important;
    color: white !important;
  }

  /* Don't allow button labels to wrap (keeps top bar buttons single-line, including popovers). */
  button {
    white-space: nowrap !important;
  }

  /* Hide the internal Filters submit button (Enter-to-apply). */
  div[data-testid="stForm"] button[aria-label="__AF_APPLY__"],
  div[data-testid="stForm"] button[title="__AF_APPLY__"],
  div[data-testid="stForm"] button[title="__AF_APPLY__"] {
    display: none !important;
  }

  /* Fallback: hide any form button with our key prefix (Streamlit uses keys in element IDs). */
  div[data-testid="stForm"] [id*="af_filters"][id*="submit::"] {
    display: none !important;
  }

  /* Truncate long button text (helps keep Filters left panel width stable). */
  button p {
    overflow: hidden !important;
    text-overflow: ellipsis !important;
  }

  /* Filters field list: keep each radio option on one line. */
  div[data-testid="stRadio"] label p {
    white-space: nowrap !important;
  }

  /* Avoid nested scrollbars: the surrounding container provides vertical scrolling. */
  div[data-testid="stRadio"] {
    overflow: visible !important;
  }

  /* Place the Filters icon to the right of the text (best-effort; DOM may vary by Streamlit version). */
  button[aria-label^="filters"] > div,
  button[title^="filters"] > div {
    display: flex !important;
    flex-direction: row-reverse !important;
    flex-wrap: nowrap !important;
    gap: 0.25rem !important;
    align-items: center !important;
  }

  button[kind="primary"]:hover,
  div[data-testid="baseButton-primary"] > button:hover {
    background: #15803d !important;
    border-color: #15803d !important;
    color: white !important;
  }

  section.main > div.block-container {
    padding-top: 0.25rem;
    padding-bottom: 1rem;
  }

  /* Improve dark-theme styling for st.dataframe. */
  div[data-testid="stDataFrame"],
  div[data-testid="stDataEditor"] {
    background: transparent !important;
  }
  div[data-testid="stDataFrame"] [role="grid"],
  div[data-testid="stDataEditor"] [role="grid"] {
    background: transparent !important;
  }
  div[data-testid="stDataFrame"] [role="gridcell"],
  div[data-testid="stDataEditor"] [role="gridcell"],
  div[data-testid="stDataFrame"] [role="columnheader"],
  div[data-testid="stDataEditor"] [role="columnheader"] {
    color: inherit !important;
    background: transparent !important;
  }

  /* Hide copy-to-clipboard icons in code blocks (st.code / fenced blocks in some versions). */
  div[data-testid="stCodeBlock"] button[title*="Copy"],
  div[data-testid="stCodeBlock"] button[aria-label*="Copy"],
  div[data-testid="stCodeBlock"] button[title*="clipboard"],
  div[data-testid="stCodeBlock"] button[aria-label*="clipboard"],
  div[data-testid="stMarkdownContainer"] pre button[title*="Copy"],
  div[data-testid="stMarkdownContainer"] pre button[aria-label*="Copy"] {
    display: none !important;
  }

</style>
""",
        unsafe_allow_html=True,
    )

    if toolbar_mode and str(toolbar_mode).lower() == "minimal":
        st.markdown(
            """
<style>
  header[data-testid="stHeader"],
  div[data-testid="stToolbar"],
  div[data-testid="stDecoration"],
  div[data-testid="stStatusWidget"] {
    display: none !important;
  }
</style>
""",
            unsafe_allow_html=True,
        )
