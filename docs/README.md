# Polaris Documentation

Welcome to the Polaris documentation! This directory contains all documentation for the data integration platform, organized by purpose and audience.

## 📁 Folder Structure

```
docs/
├── README.md (this file)
├── reference/          # Long-term reference materials
│   ├── architecture/   # System architecture and design docs
│   ├── salesforce/     # Salesforce mapping and integration guides
│   └── data-quality/   # Data quality dashboard and configuration
├── operations/         # Day-to-day operational guides
├── sprints/           # Historical sprint documentation
└── tests/             # Test documentation
```

### Why This Structure?

- **`reference/`**: Long-term documentation that doesn't change frequently. These are the "source of truth" documents for architecture, integrations, and system design.
- **`operations/`**: Guides you'll use regularly for day-to-day operations, troubleshooting, and running the system.
- **`sprints/`**: Historical sprint retrospectives and decisions. Useful for understanding past decisions and context.
- **`tests/`**: Documentation about testing strategies and coverage.

## 🚀 Quick Links

### Most Commonly Accessed

- **[Commands Reference](operations/commands.md)** - CLI commands for running imports, managing workers, and troubleshooting
- **[Salesforce Mapping Guide](reference/salesforce/salesforce-mapping-guide.md)** - How to extend Salesforce field mappings
- **[Data Quality Dashboard](reference/data-quality/data-quality-dashboard.md)** - Field-level completeness metrics and health scores
- **[Importer Feature Flag](operations/importer-feature-flag.md)** - Enabling and configuring the importer

### Architecture & Design

- **[Platform Overview](reference/architecture/data-integration-platform-overview.md)** - High-level architecture, data layers, and design principles
- **[Technical Documentation](reference/architecture/data-integration-platform-tech-doc.md)** - Complete backlog, sprint details, and implementation notes

## 👥 Documentation by Role

### For Developers

**Getting Started:**
- [Platform Overview](reference/architecture/data-integration-platform-overview.md) - Start here to understand the system architecture
- [Technical Documentation](reference/architecture/data-integration-platform-tech-doc.md) - Complete implementation details

**Extending the System:**
- [Salesforce Mapping Guide](reference/salesforce/salesforce-mapping-guide.md) - Add new fields or Salesforce objects
- [Salesforce Transforms Reference](reference/salesforce/salesforce-transforms-reference.md) - Available transform functions
- [Salesforce Mapping Examples](reference/salesforce/salesforce-mapping-examples.md) - Copy/paste recipes

**Reference:**
- [Salesforce Field Mapping Summary](reference/salesforce/salesforce-field-mapping-summary.md) - Where each Salesforce field is stored
- [Salesforce Fields Location Guide](reference/salesforce/salesforce-fields-location-guide.md) - Field location reference
- [Salesforce Mapping Gap Analysis](reference/salesforce/salesforce-mapping-gap-analysis.md) - Missing fields and priorities
- [Salesforce Mapping Testing Checklist](reference/salesforce/salesforce-mapping-testing-checklist.md) - Testing guidance

### For Operators

**Daily Operations:**
- [Commands Reference](operations/commands.md) - All CLI commands with examples
- [Importer Feature Flag](operations/importer-feature-flag.md) - Configuration and troubleshooting
- [Importer Merge Runbook](operations/importer-merge-runbook.md) - Managing duplicate merges

**Troubleshooting:**
- [Importer Duplicate Check Optimizations](operations/importer-duplicate-check-optimizations.md) - Performance tuning
- [Commands Reference - Troubleshooting](operations/commands.md#troubleshooting) - Common issues and solutions

**Process:**
- [Definition of Ready (DoR)](operations/importer-dor.md) - Checklist for importer tickets
- [Definition of Done (DoD)](operations/importer-dod.md) - Release checklist

### For Data Stewards

**Working with Data:**
- [Importer Merge Runbook](operations/importer-merge-runbook.md) - Reviewing and merging duplicates
- [Data Quality Dashboard](reference/data-quality/data-quality-dashboard.md) - Monitoring field completeness
- [Data Quality Field Configuration](reference/data-quality/data-quality-field-configuration.md) - Configuring field-level metrics

### For Project Managers

**Project Context:**
- [Sprint Retrospectives](sprints/) - Historical sprint learnings and decisions
  - [Sprint 1](sprints/sprint1-retrospective.md)
  - [Sprint 2](sprints/sprint2-retrospective.md)
  - [Sprint 3](sprints/sprint3-retrospective.md)
  - [Sprint 4](sprints/sprint4-retrospective.md)
  - [Sprint 5](sprints/sprint5-retrospective.md)
- [Sprint 5 Decisions](sprints/sprint5-survivorship-decisions.md) - Survivorship and threshold decisions
- [Sprint 5 Analytics Alignment](sprints/sprint5-analytics-alignment.md) - Metrics and dashboard requirements
- [Salesforce Mapping Gap Analysis](reference/salesforce/salesforce-mapping-gap-analysis.md) - Missing fields and priorities

## 📚 Reference Documentation

### Architecture

- **[Platform Overview](reference/architecture/data-integration-platform-overview.md)** - High-level architecture, data layers, pipeline flow, and design principles
- **[Technical Documentation](reference/architecture/data-integration-platform-tech-doc.md)** - Complete backlog, sprint details, implementation notes, and roadmap

### Salesforce Integration

All Salesforce-related documentation is grouped in `reference/salesforce/`:

- **[Mapping Guide](reference/salesforce/salesforce-mapping-guide.md)** - Architecture and how to extend mappings
- **[Transforms Reference](reference/salesforce/salesforce-transforms-reference.md)** - Available transform functions
- **[Mapping Examples](reference/salesforce/salesforce-mapping-examples.md)** - Real-world examples and recipes
- **[Field Mapping Summary](reference/salesforce/salesforce-field-mapping-summary.md)** - Where each field is stored
- **[Fields Location Guide](reference/salesforce/salesforce-fields-location-guide.md)** - Field location reference
- **[Gap Analysis](reference/salesforce/salesforce-mapping-gap-analysis.md)** - Missing fields and implementation priorities
- **[Testing Checklist](reference/salesforce/salesforce-mapping-testing-checklist.md)** - Testing guidance

### Data Quality

- **[Data Quality Dashboard](reference/data-quality/data-quality-dashboard.md)** - Field-level completeness metrics, API reference, and usage
- **[Data Quality Field Configuration](reference/data-quality/data-quality-field-configuration.md)** - Configuring field-level metrics

## 🔧 Operational Guides

All operational guides are in `operations/`:

- **[Commands](operations/commands.md)** - CLI command reference with troubleshooting
- **[Importer Feature Flag](operations/importer-feature-flag.md)** - Configuration and troubleshooting
- **[Importer Merge Runbook](operations/importer-merge-runbook.md)** - Managing duplicate merges
- **[Importer Duplicate Check Optimizations](operations/importer-duplicate-check-optimizations.md)** - Performance tuning
- **[Definition of Ready (DoR)](operations/importer-dor.md)** - Checklist for importer tickets
- **[Definition of Done (DoD)](operations/importer-dod.md)** - Release checklist

## 📖 Sprint Documentation

Historical sprint documentation is archived in `sprints/`:

- **[Sprint 1 Retrospective](sprints/sprint1-retrospective.md)** - CSV Adapter + ELT Skeleton
- **[Sprint 2 Retrospective](sprints/sprint2-retrospective.md)** - Runs Dashboard + DQ Inbox
- **[Sprint 3 Retrospective](sprints/sprint3-retrospective.md)** - Idempotency + Deterministic Dedupe
- **[Sprint 4 Retrospective](sprints/sprint4-retrospective.md)** - Salesforce Adapter
- **[Sprint 5 Retrospective](sprints/sprint5-retrospective.md)** - Fuzzy Dedupe + Merge UI
- **[Sprint 5 Survivorship Decisions](sprints/sprint5-survivorship-decisions.md)** - Threshold and policy decisions
- **[Sprint 5 Analytics Alignment](sprints/sprint5-analytics-alignment.md)** - Metrics and dashboard requirements
- **[Sprint 5 Merge Logging Audit](sprints/sprint5-merge-logging-audit.md)** - Audit logging details

## 🧪 Test Documentation

- **[What is Tested](tests/WHAT_IS_TESTED.md)** - Overview of test coverage
- **[Test Coverage](tests/TEST_COVERAGE.md)** - Detailed coverage information

## 🔍 Finding What You Need

### By Task

- **Running an import**: [Commands Reference](operations/commands.md)
- **Configuring the importer**: [Importer Feature Flag](operations/importer-feature-flag.md)
- **Adding a Salesforce field**: [Salesforce Mapping Guide](reference/salesforce/salesforce-mapping-guide.md)
- **Reviewing duplicates**: [Importer Merge Runbook](operations/importer-merge-runbook.md)
- **Checking data quality**: [Data Quality Dashboard](reference/data-quality/data-quality-dashboard.md)
- **Understanding architecture**: [Platform Overview](reference/architecture/data-integration-platform-overview.md)

### By File Type

- **Architecture docs**: `reference/architecture/`
- **Salesforce docs**: `reference/salesforce/`
- **Data quality docs**: `reference/data-quality/`
- **Operational guides**: `operations/`
- **Sprint docs**: `sprints/`

## 📝 Contributing to Documentation

When adding or updating documentation:

1. **Place files in the appropriate folder** based on their purpose:
   - Reference materials → `reference/`
   - Operational guides → `operations/`
   - Sprint docs → `sprints/`

2. **Update cross-references** when moving or renaming files

3. **Update this README** if adding new major sections or reorganizing

4. **Use consistent formatting** - follow the style of existing docs

## 🔗 External Resources

- **Golden Dataset**: `ops/testdata/importer_golden_dataset_v0/README.md` - Test data documentation
- **Mapping Files**: `config/mappings/` - YAML mapping specifications

---

**Last Updated**: Documentation reorganized November 2025

