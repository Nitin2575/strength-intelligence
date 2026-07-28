# System Architecture

## Purpose

The systems layer explains how information moves from raw data to a user-facing recommendation.

## High-Level Architecture

```mermaid
flowchart LR
    A[Apple Health Export] --> C[Ingestion]
    B[Workout Journal Export] --> C
    C --> D[Cleaning and Standardization]
    D --> E[(Analytics Database)]
    E --> F[SQL Metrics]
    E --> G[Python Analysis]
    F --> H[Insight Service]
    G --> H
    H --> I[Recommendation Rules]
    I --> J[AI Explanation Layer]
    J --> K[Web Application]
```

## Main Components

### 1. Ingestion

Reads exported Apple Health and workout journal data.

### 2. Cleaning

- Standardizes dates
- Removes duplicates
- Normalizes exercise names
- Checks missing values
- Converts units

### 3. Analytics Database

Stores structured daily health, workout, set, metric, and recommendation records.

### 4. Metric Layer

Provides consistent definitions for:

- Session performance
- Plan completion
- Progressive overload
- Recent training load
- Personal recovery baseline

### 5. Insight Service

Finds patterns and creates structured findings.

Example:

```json
{
  "insight_type": "sleep_performance",
  "exercise": "Barbell Squat",
  "effect": -0.07,
  "confidence": "moderate",
  "supporting_sessions": 14
}
```

### 6. Recommendation Layer

Maps findings to cautious actions such as:

- Progress load
- Repeat load
- Reduce planned volume
- Review recovery
- Collect more data

### 7. Explanation Layer

Turns structured findings into clear language. It does not calculate the core metrics itself.

## System Design Principle

> Calculations should be deterministic. AI should explain the result, not invent it.

## Request Flow

```mermaid
sequenceDiagram
    participant U as User
    participant UI as Web App
    participant API as Product API
    participant DB as Analytics Database
    participant R as Recommendation Engine
    participant AI as Explanation Layer

    U->>UI: Opens session analysis
    UI->>API: Request session insight
    API->>DB: Load session and baseline
    DB-->>API: Return structured data
    API->>R: Calculate recommendation
    R-->>API: Return action and evidence
    API->>AI: Create plain-language explanation
    AI-->>API: Return explanation
    API-->>UI: Display insight card
```
