"""App loading and hydration fallback components."""

from __future__ import annotations

import reflex as rx


def hydration_fallback_script() -> rx.Component:
    """Inject min-CSS and loading UI that displays before React hydrates.

    This prevents the "blank screen" during module loading/hydration.
    The loader will be hidden once React takes over via CSS class toggle.
    """
    return rx.script(
        """
        // Show loading fallback before React hydration
        (function() {
            // Create fallback container if not already present
            if (!document.getElementById('hydration-fallback')) {
                const fallback = document.createElement('div');
                fallback.id = 'hydration-fallback';
                fallback.className = 'hydration-loading';
                fallback.innerHTML = `
                    <div class="hydration-spinner">
                        <div class="spinner-ring"></div>
                        <p class="loading-text">Loading app...</p>
                    </div>
                `;
                document.body.appendChild(fallback);

                // Hide fallback once React has mounted (via class toggle)
                // This is triggered by the main app component
                const interval = setInterval(() => {
                    if (document.body.classList.contains('react-mounted')) {
                        fallback.classList.add('hydration-done');
                        clearInterval(interval);
                    }
                }, 50);

                // Fallback timeout - hide after 10s even if React doesn't signal
                setTimeout(() => {
                    fallback.classList.add('hydration-done');
                }, 10000);
            }
        })();
        """,
    )


def hydration_styles() -> rx.Component:
    """Inject CSS for the hydration fallback loader."""
    return rx.script(
        """
        (function () {
            if (document.getElementById('pp-hydration-style')) {
                return;
            }
            const style = document.createElement('style');
            style.id = 'pp-hydration-style';
            style.textContent = `
                body {
                    margin: 0;
                    padding: 0;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Roboto", "Oxygen", "Ubuntu", "Cantarell", "Fira Sans", "Droid Sans", "Helvetica Neue", sans-serif;
                }

                #hydration-fallback {
                    position: fixed;
                    top: 0;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    background: radial-gradient(1200px 500px at 15% -5%, #d8e8ff 0%, rgba(216, 232, 255, 0) 60%),
                                radial-gradient(1000px 450px at 90% 0%, #d7fff0 0%, rgba(215, 255, 240, 0) 55%),
                                #eef3fb;
                    z-index: 9999;
                    opacity: 1;
                    transition: opacity 300ms ease-out, visibility 300ms ease-out;
                    visibility: visible;
                }

                #hydration-fallback.hydration-done {
                    opacity: 0;
                    visibility: hidden;
                    pointer-events: none;
                }

                .hydration-spinner {
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 20px;
                }

                .spinner-ring {
                    width: 48px;
                    height: 48px;
                    border: 3px solid rgba(10, 102, 255, 0.1);
                    border-top-color: #0a66ff;
                    border-right-color: #0a66ff;
                    border-radius: 50%;
                    animation: pp-hydration-spin 1s linear infinite;
                }

                @keyframes pp-hydration-spin {
                    to {
                        transform: rotate(360deg);
                    }
                }

                .loading-text {
                    margin: 0;
                    font-size: 14px;
                    font-weight: 500;
                    color: #0a66ff;
                    letter-spacing: 0.5px;
                }
            `;
            document.head.appendChild(style);
        })();
        """,
    )


def app_wrapper(*children, **props) -> rx.Component:
    """Wraps main app content and signals when React hydration is complete.

    This should wrap the entire app content to ensure the hydration
    fallback triggers the 'react-mounted' class when ready.
    """
    return rx.fragment(
        hydration_fallback_script(),
        hydration_styles(),
        rx.script(
            """
            // Signal that React has mounted
            document.body.classList.add('react-mounted');
            """
        ),
        rx.box(
            *children,
            **props,
        ),
    )
