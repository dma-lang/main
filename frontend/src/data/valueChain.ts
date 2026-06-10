// Value-chain atlas data — the 8 universal MECE clusters (VCC-01..08) and the per-subvertical
// stage pipelines, extracted from the prototype's CIA_APP config (scripts/extract_prototype.py ->
// .prototype/named/config.js). The catalogue's subcap_vcc mapping (sheet 21) is not ingested yet,
// so this committed constant is the rendering source; live subcap names/links join via the
// catalogue API at render time. Replace with GET /api/catalogue/{v}/value-chain when seeded.

export interface VccCluster {
  code: string;
  name: string;
  blurb: string;
  count: number;
}

export interface VcStage {
  stage: string;
  subs: string[];
}

export const VALUE_CHAIN: VccCluster[] = [
  {
    "code": "VCC-01",
    "name": "Acquire & onboard",
    "blurb": "Lead, KYC, account open",
    "count": 118
  },
  {
    "code": "VCC-02",
    "name": "Engage & serve",
    "blurb": "Service, advice, support",
    "count": 164
  },
  {
    "code": "VCC-03",
    "name": "Originate & underwrite",
    "blurb": "Apply, decision, fund",
    "count": 132
  },
  {
    "code": "VCC-04",
    "name": "Transact & process",
    "blurb": "Payments, posting, recon",
    "count": 96
  },
  {
    "code": "VCC-05",
    "name": "Manage risk & comply",
    "blurb": "Risk, fraud, regulatory",
    "count": 124
  },
  {
    "code": "VCC-06",
    "name": "Operate & service ops",
    "blurb": "Back office, exceptions",
    "count": 71
  },
  {
    "code": "VCC-07",
    "name": "Analyse & decide",
    "blurb": "Reporting, insight, BI",
    "count": 98
  },
  {
    "code": "VCC-08",
    "name": "Govern & enable",
    "blurb": "Data, platform, controls",
    "count": 48
  }
];

/** Stage pipelines keyed "VCC-xx|SV" — the prototype maps the Commercial Lending exemplar. */
export const VC_STAGES: Record<string, VcStage[]> = {
  "VCC-01|CL": [
    {
      "stage": "Lead & capture",
      "subs": [
        "P2C1.1.1",
        "P2C1.1.2"
      ]
    },
    {
      "stage": "Identity & KYC",
      "subs": [
        "P2C2.1.1",
        "P2C2.1.2"
      ]
    },
    {
      "stage": "Account open",
      "subs": [
        "P2C2.1.3",
        "P2C2.1.4"
      ]
    },
    {
      "stage": "Activation",
      "subs": [
        "P4C1.1.1"
      ]
    }
  ],
  "VCC-02|CL": [
    {
      "stage": "Self-service",
      "subs": [
        "P2C3.1.1",
        "P2C3.1.2"
      ]
    },
    {
      "stage": "Assisted service",
      "subs": [
        "P2C3.1.3",
        "P2C3.1.4"
      ]
    },
    {
      "stage": "Advice & guidance",
      "subs": [
        "P2C4.1.1",
        "P2C4.1.2"
      ]
    },
    {
      "stage": "Voice of customer",
      "subs": [
        "P2C3.1.5"
      ]
    }
  ],
  "VCC-03|CL": [
    {
      "stage": "Application intake",
      "subs": [
        "P2C2.1.1",
        "P2C2.1.2"
      ]
    },
    {
      "stage": "Credit decisioning",
      "subs": [
        "P1C2.1.1",
        "P1C2.1.2"
      ]
    },
    {
      "stage": "Documentation",
      "subs": [
        "P3C1.1.1",
        "P3C1.1.2"
      ]
    },
    {
      "stage": "Funding & booking",
      "subs": [
        "P3C2.1.1",
        "P3C2.1.2"
      ]
    }
  ],
  "VCC-04|CL": [
    {
      "stage": "Payments",
      "subs": [
        "P3C1.1.1",
        "P3C1.1.2"
      ]
    },
    {
      "stage": "Posting & recon",
      "subs": [
        "P3C1.1.3",
        "P3C1.1.4"
      ]
    },
    {
      "stage": "Settlement",
      "subs": [
        "P3C2.1.1"
      ]
    }
  ],
  "VCC-05|CL": [
    {
      "stage": "Risk governance",
      "subs": [
        "P1C2.1.1",
        "P1C2.1.2"
      ]
    },
    {
      "stage": "Fraud controls",
      "subs": [
        "P3C2.1.1",
        "P3C2.1.2"
      ]
    },
    {
      "stage": "Regulatory",
      "subs": [
        "P3C3.1.1",
        "P3C3.1.2"
      ]
    },
    {
      "stage": "Surveillance",
      "subs": [
        "P3C3.1.3"
      ]
    }
  ],
  "VCC-06|CL": [
    {
      "stage": "Back office",
      "subs": [
        "P3C1.1.1",
        "P3C1.1.2"
      ]
    },
    {
      "stage": "Exception mgmt",
      "subs": [
        "P3C1.1.3"
      ]
    },
    {
      "stage": "Vendor ops",
      "subs": [
        "P3C4.1.1",
        "P3C4.1.2"
      ]
    }
  ],
  "VCC-07|CL": [
    {
      "stage": "Reporting & BI",
      "subs": [
        "P4C2.1.1",
        "P4C2.1.2"
      ]
    },
    {
      "stage": "Advanced analytics",
      "subs": [
        "P4C2.2.1",
        "P4C2.2.2"
      ]
    },
    {
      "stage": "Insight activation",
      "subs": [
        "P4C1.1.1",
        "P4C1.1.2"
      ]
    }
  ],
  "VCC-08|CL": [
    {
      "stage": "Data & platform",
      "subs": [
        "P4C1.1.1",
        "P4C1.1.2"
      ]
    },
    {
      "stage": "Integration",
      "subs": [
        "P4C3.1.1",
        "P4C3.1.2"
      ]
    },
    {
      "stage": "Controls",
      "subs": [
        "P4C4.1.1",
        "P4C4.1.2"
      ]
    }
  ]
};
