"""Dataset Builder — turns observations into structured, quality-scored, labelled
training data. Completely independent of the AI layer: this package must never
import from backend.ai. The AI *consumes* observations; the Dataset Builder
*consumes observations and produces datasets*. Different responsibilities.
"""
