Orchestrator (ศูนย์บัญชาการ)

หน้าที่
	•	รับ request จากภายนอก
	•	generate / propagate X-Correlation-ID
	•	เรียก Technical / Fundamental Agent
	•	normalize response schema
	•	ส่งผลรวมให้ Learning Agent

---

### ❗ Best Practices for AI/ML Models (แนวทางปฏิบัติที่ดีที่สุดสำหรับโมเดล AI/ML)

To ensure that the Docker images remain small, fast, and secure, **AI/ML models, datasets, or checkpoints should NOT be copied directly into the image.** Including these large files directly into the image leads to several problems:
*   **Large Image Size:** Models can be hundreds of megabytes or even gigabytes, which dramatically increases the image size.
*   **Slow Builds & Transfers:** Larger images are slower to build, push to a registry, and pull onto a server.
*   **Tight Coupling:** The model is "baked in" to the application. Updating the model requires rebuilding and redeploying the entire service.

#### Recommended Approach: Externalize Models

The best practice is to load models at runtime from an external source. This keeps the application image small and decouples the model lifecycle from the application lifecycle.

**Options for Externalizing Models:**

1.  **Cloud Storage (e.g., AWS S3, Google Cloud Storage):**
    *   **How it works:** Store your model files in a cloud storage bucket. At application startup, your code downloads the model file into memory or a temporary local directory.
    *   **Best for:** General-purpose, cost-effective storage.

2.  **Model Registries (e.g., Hugging Face Hub, MLflow, AWS SageMaker Model Registry):**
    *   **How it works:** Use a dedicated service to host and version your models. Your application can pull a specific model version using an SDK or API call.
    *   **Best for:** Projects that require robust model versioning, tracking, and governance.

3.  **Dedicated Model Serving API:**
    *   **How it works:** Deploy your model as its own microservice (e.g., using TensorFlow Serving, TorchServe, or a custom FastAPI server). Your main application then calls this service via an API to get predictions.
    *   **Best for:** Large models or situations where the model requires specific hardware (like GPUs) that the main application doesn't need.
