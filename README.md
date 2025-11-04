# ⚙️ Proyecto: Sistema de Monitoreo IoT Aplicado a Cultivos de Lechuga Hidropónica

---

## 🧠 Funcionamiento General

El sistema está conformado por **5 módulos** que trabajan de manera conjunta para el monitoreo integral del cultivo:

- **4 módulos emisores**: se encargan de recolectar las variables de cada zona de medición (pH, conductividad eléctrica, temperatura, humedad y niveles de agua) y transmitirlas de forma inalámbrica.  
- **1 módulo receptor (principal)**: centraliza toda la información recibida de los emisores y la envía a una **máquina virtual** a través del **puerto TCP:22**.

En la máquina virtual, los datos son procesados mediante dos rutas principales:
- **latest**: muestra en tiempo real los valores más recientes en la aplicación web, permitiendo la visualización inmediata del estado del sistema.  
- **pending_file**: almacena temporalmente los datos recibidos durante intervalos de **15 minutos**. Transcurrido este tiempo, los valores se **promedian** y se envían a la base de datos **MongoDB** para su almacenamiento histórico.

Desde MongoDB, los datos son posteriormente consultados por la página web, donde se representan en **gráficas y tablas dinámicas**, brindando una visión clara del comportamiento de las variables del sistema en el tiempo.

---


## 👥 Autores

- **Alejandro Díaz Igua**  
- **David Eraso García**  
- **Ana Sofía Muñoz Villota**  
- **Ivette Camila Yepez Morán**

---

📍 *Proyecto académico.*